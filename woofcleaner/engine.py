"""Rule engine: detect -> expand -> enumerate -> (analyse | clean).

Mirrors the pipeline seen in CCleaner 7's service (Windows.Cleaning log
category): rules are turned into tasks, each task is applied in 'Analyse' or
'Clean' mode, and every task returns a per-rule result (files / bytes / errors).
"""
from __future__ import annotations

import itertools
import json
import os
import re
import stat
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from . import winutil
from .rules import Action, FileKey, OnFile, Rule, RuleSet

MAX_LISTED_ITEMS = 2000
SUPPORTED_ON_FILE = {"filedelete", "filedeleteifolderthan"}


class Mode:
    ANALYSE = "analyse"
    CLEAN = "clean"


@dataclass
class RuleResult:
    rule_id: str
    name: str
    mode: str
    applicable: bool = True
    files: int = 0
    bytes: int = 0
    dirs_removed: int = 0
    reg_items: int = 0
    skipped_locked: int = 0
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    items: list[tuple[str, int]] = field(default_factory=list)

    @property
    def found_anything(self) -> bool:
        return bool(self.files or self.reg_items or self.bytes)


# ---- path expansion ---------------------------------------------------------

_ENV_RE = re.compile(r"%([A-Za-z0-9_]+)%")
_VAR_RE = re.compile(r"<([A-Za-z0-9_]+)>")


def expand_env(path: str, env: dict[str, str]) -> str | None:
    """Expand %VAR%; None if a variable is unknown/empty (rule part is skipped)."""
    missing = False

    def sub(m: re.Match) -> str:
        nonlocal missing
        val = env.get(m.group(1).upper())
        if not val:
            missing = True
            return m.group(0)
        return val

    out = _ENV_RE.sub(sub, path)
    return None if missing else out


def expand_variants(path: str, rule_vars: dict[str, list[str]]) -> list[str]:
    """Expand <RULE_VAR> references (each may hold several alternative paths)."""
    names = _VAR_RE.findall(path)
    if not names:
        return [path]
    pools = []
    for n in names:
        vals = rule_vars.get(n.upper())
        if not vals:
            return []
        pools.append(vals)
    out = []
    for combo in itertools.product(*pools):
        p = path
        for n, v in zip(names, combo):
            p = p.replace(f"<{n}>", v, 1)
        out.append(p)
    return out


def _wild(pattern: str) -> re.Pattern:
    if pattern == "*.*":
        pattern = "*"
    rx = "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in pattern)
    return re.compile(rx + r"\Z", re.IGNORECASE | re.DOTALL)


def glob_paths(pattern: str) -> list[str]:
    """Expand * / ? in any path segment; returns existing paths."""
    drive, rest = os.path.splitdrive(pattern)
    segs = [s for s in re.split(r"[\\/]+", rest) if s]
    current = [(drive + os.sep) if drive else os.sep]
    for seg in segs:
        nxt: list[str] = []
        for base in current:
            if "*" in seg or "?" in seg:
                rx = _wild(seg)
                try:
                    with os.scandir(base) as it:
                        nxt += [e.path for e in it if rx.match(e.name)]
                except OSError:
                    pass
            else:
                p = os.path.join(base, seg)
                if os.path.lexists(p):
                    nxt.append(p)
        current = nxt
        if not current:
            break
    return current


def _is_reparse(path: str) -> bool:
    try:
        st = os.lstat(path)
    except OSError:
        return True
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400)


def _is_drive_root(path: str) -> bool:
    p = os.path.normpath(path)
    return os.path.dirname(p) == p or re.fullmatch(r"[A-Za-z]:\\?", p) is not None


# ---- context ----------------------------------------------------------------

@dataclass
class Context:
    rules: RuleSet
    env: dict[str, str] = field(default_factory=winutil.default_env)
    mode: str = Mode.ANALYSE
    cancel: threading.Event = field(default_factory=threading.Event)
    progress: Callable[[str], None] = lambda msg: None
    backup_dir: Path | None = None
    running: set[str] | None = None
    now: float = field(default_factory=time.time)
    # Test hook: pretend the OS version/features so rules can be exercised anywhere.
    os_version: tuple[int, int] | None = None

    def running_processes(self) -> set[str]:
        if self.running is None:
            self.running = winutil.running_processes()
        return self.running


# ---- detection --------------------------------------------------------------

def _variants(raw: str, ctx: Context) -> list[str]:
    out = []
    for v in expand_variants(raw, ctx.rules.vars):
        e = expand_env(v, ctx.env)
        if e:
            out.append(e)
    return out


def is_applicable(rule: Rule, ctx: Context) -> bool:
    if rule.detect_os and (ctx.os_version or winutil.windows_version()) < rule.detect_os:
        return False
    checks: list[bool] = []
    if rule.detect:
        checks.append(any(winutil.reg_key_exists(d) for d in rule.detect))
    if rule.detect_files:
        found = False
        for raw in rule.detect_files:
            if any(glob_paths(p) for p in _variants(raw, ctx)):
                found = True
                break
        checks.append(found)
    return all(checks) if checks else True


# ---- file cleaning ----------------------------------------------------------

def _excluded(path: str, rule: Rule, ctx: Context) -> bool:
    p = os.path.normcase(path)
    for ex in rule.excludes:
        for v in _variants(ex.path, ctx):
            if ex.kind == "FILE":
                if _wild(os.path.normcase(v)).match(p):
                    return True
            elif ex.kind == "PATH":
                base = os.path.normcase(os.path.normpath(v)).rstrip("\\")
                if p == base or p.startswith(base + "\\"):
                    return True
    return False


def _per_file_policy(name: str, rule: Rule) -> tuple[str, float | None]:
    """OnFile handler for this file: ('delete', None) or ('older', seconds)."""
    for of in rule.on_file:
        if _wild(of.pattern).match(name):
            h = of.handler.lower()
            if h == "filedeleteifolderthan":
                m = re.fullmatch(r"(\d+)\s*(day|days|hour|hours)", (of.arg or "").strip(), re.I)
                if not m:
                    return ("skip", None)
                n, unit = int(m.group(1)), m.group(2).lower()
                return ("older", n * (86400 if unit.startswith("day") else 3600))
            return ("delete", None)
    return ("delete", None)


def _delete_file(path: str) -> None:
    try:
        os.remove(path)
    except PermissionError:
        os.chmod(path, stat.S_IWRITE)
        os.remove(path)


def _clean_filekey(fk: FileKey, rule: Rule, ctx: Context, res: RuleResult) -> None:
    clean = ctx.mode == Mode.CLEAN
    for raw in _variants(fk.path, ctx):
        for root in glob_paths(raw):
            if ctx.cancel.is_set():
                return
            if _is_drive_root(root):
                res.errors.append(f"refused: drive root {root}")
                continue
            if fk.recurse and len(Path(root).parts) < 3:
                res.errors.append(f"refused: recursive rule on shallow path {root}")
                continue
            if _is_reparse(root) or not os.path.isdir(root):
                continue
            pats = [_wild(p) for p in fk.patterns]
            walker = _walk(root) if fk.recurse else [(root, _listfiles(root))]
            for dirpath, filenames in walker:
                if ctx.cancel.is_set():
                    return
                for fn in filenames:
                    if not any(p.match(fn) for p in pats):
                        continue
                    full = os.path.join(dirpath, fn)
                    if _excluded(full, rule, ctx):
                        continue
                    try:
                        st = os.lstat(full)
                    except OSError:
                        continue
                    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
                        continue
                    action, secs = _per_file_policy(fn, rule)
                    if action == "skip":
                        continue
                    if action == "older" and ctx.now - st.st_mtime < secs:
                        continue
                    if clean:
                        try:
                            _delete_file(full)
                        except OSError as e:
                            res.skipped_locked += 1
                            if len(res.errors) < 50:
                                res.errors.append(f"{full}: {e.strerror or e}")
                            continue
                    res.files += 1
                    res.bytes += st.st_size
                    if len(res.items) < MAX_LISTED_ITEMS:
                        res.items.append((full, st.st_size))
                if fk.recurse and dirpath != root and clean:
                    try:
                        os.rmdir(dirpath)  # only succeeds when now empty
                        res.dirs_removed += 1
                    except OSError:
                        pass
            if fk.remove_self and clean:
                try:
                    os.rmdir(root)
                    res.dirs_removed += 1
                except OSError:
                    pass


def _walk(root: str):
    """Bottom-up (dirpath, filenames); never enters or touches symlinks/junctions."""
    files: list[str] = []
    dirs: list[str] = []
    try:
        with os.scandir(root) as it:
            for e in it:
                try:
                    if _is_reparse(e.path):
                        continue
                    if e.is_dir(follow_symlinks=False):
                        dirs.append(e.path)
                    elif e.is_file(follow_symlinks=False):
                        files.append(e.name)
                except OSError:
                    pass
    except OSError:
        return
    for d in dirs:
        yield from _walk(d)
    yield root, files


def _listfiles(root: str) -> list[str]:
    try:
        with os.scandir(root) as it:
            return [e.name for e in it if e.is_file(follow_symlinks=False)]
    except OSError:
        return []


# ---- registry ---------------------------------------------------------------

def _clean_regkey(rk, ctx: Context, res: RuleResult, backup: dict) -> None:
    if not winutil.IS_WINDOWS:
        return
    hive = rk.path.split("\\", 1)[0].upper()
    if hive not in ("HKCU", "HKEY_CURRENT_USER"):
        res.notes.append(f"skipped {hive} registry key (HKCU only)")
        return
    exists = winutil.reg_value_exists(rk.path, rk.value) if rk.value else winutil.reg_key_exists(rk.path)
    if not exists:
        return
    res.reg_items += 1
    if ctx.mode != Mode.CLEAN:
        return
    try:
        h, sub = winutil._split_reg(rk.path)
        if rk.value is None:
            backup[rk.path] = winutil.reg_dump(h, sub)
        else:
            import winreg
            with winreg.OpenKey(h, sub) as k:
                v, t = winreg.QueryValueEx(k, rk.value)
            backup[rk.path + "|" + rk.value] = [t, v.hex() if isinstance(v, bytes) else v]
        winutil.reg_delete(rk.path, rk.value)
    except OSError as e:
        res.reg_items -= 1
        res.errors.append(f"{rk.path}: {e}")


# ---- built-in actions -------------------------------------------------------

def _action(act: Action, rule: Rule, ctx: Context, res: RuleResult) -> None:
    name = act.name.lower()
    clean = ctx.mode == Mode.CLEAN
    if not winutil.IS_WINDOWS:
        res.notes.append(f"action {act.name} needs Windows")
        return
    if name == "emptyrecyclebin":
        size, count = winutil.recycle_bin_info()
        if count:
            res.files += count
            res.bytes += size
            if clean:
                winutil.empty_recycle_bin()
    elif name == "cleandnscache":
        res.notes.append("DNS resolver cache" + (" flushed" if clean else " will be flushed"))
        if clean:
            winutil.flush_dns()
        res.reg_items += 0
    elif name == "cleanclipboard":
        res.notes.append("clipboard" + (" cleared" if clean else " will be cleared"))
        if clean:
            winutil.clear_clipboard()
    elif name == "shelladdtorecentdocuments" or name == "shelladdtorecentdocs":
        res.notes.append("Recent Documents list" + (" cleared" if clean else " will be cleared"))
        if clean:
            winutil.clear_recent_documents()
    elif name == "removeemptydirectories":
        for raw in _variants(act.arg or "", ctx):
            for root in glob_paths(raw):
                if len(Path(root).parts) < 3 or _is_reparse(root):
                    continue
                for dp, _fn in _walk(root):
                    if dp == root:
                        continue
                    try:
                        if not os.listdir(dp):
                            if clean:
                                os.rmdir(dp)
                            res.dirs_removed += 1
                    except OSError:
                        pass
    else:
        res.notes.append(f"unsupported action '{act.name}' (skipped)")


# ---- driver -----------------------------------------------------------------

def run_rule(rule: Rule, ctx: Context, backup: dict | None = None) -> RuleResult:
    res = RuleResult(rule.id, rule.name, ctx.mode)
    backup = backup if backup is not None else {}
    if not is_applicable(rule, ctx):
        res.applicable = False
        return res
    unsupported = [o.handler for o in rule.on_file if o.handler.lower() not in SUPPORTED_ON_FILE]
    if unsupported:
        res.notes.append(f"unsupported OnFile handler(s): {', '.join(sorted(set(unsupported)))}")
    if rule.active_processes:
        live = ctx.running_processes()
        busy = [p for p in rule.active_processes if p.lower() in live]
        if busy:
            res.notes.append(f"{', '.join(busy)} is running - cleaning will be suboptimal")
    for fk in rule.file_keys:
        _clean_filekey(fk, rule, ctx, res)
    for rk in rule.reg_keys:
        if ctx.cancel.is_set():
            break
        _clean_regkey(rk, ctx, res, backup)
    for act in rule.actions:
        if ctx.cancel.is_set():
            break
        try:
            _action(act, rule, ctx, res)
        except Exception as e:  # keep going: one failing action must not abort the run
            res.errors.append(f"{act.name}: {e}")
    return res


def run(rule_ids: Iterable[str], ctx: Context) -> list[RuleResult]:
    by_id = ctx.rules.by_id()
    selected = [by_id[i] for i in rule_ids if i in by_id]
    results: list[RuleResult] = []
    backup: dict = {}
    for n, rule in enumerate(selected, 1):
        if ctx.cancel.is_set():
            break
        ctx.progress(f"[{n}/{len(selected)}] {ctx.mode}: {rule.name}")
        results.append(run_rule(rule, ctx, backup))
    if backup and ctx.backup_dir:
        ctx.backup_dir.mkdir(parents=True, exist_ok=True)
        out = ctx.backup_dir / f"registry_{datetime.now():%Y%m%d_%H%M%S}.json"
        out.write_text(json.dumps(backup, indent=1), encoding="utf-8")
        ctx.progress(f"registry backup written: {out}")
    return results


def human(n: int) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024 or unit == "TB":
            return f"{int(f)} {unit}" if unit == "B" else f"{f:.1f} {unit}"
        f /= 1024
    return f"{n} B"
