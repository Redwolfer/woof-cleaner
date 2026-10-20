"""Command line: python -m woofcleaner <command> ...   (run without arguments for the GUI)"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from . import __version__, winutil
from .engine import Context, Mode, human, is_applicable, run
from .paths import BACKUP_DIR, DEFAULT_RULES
from .rules import load_rules


def _ask(prompt: str, yes: bool) -> bool:
    return yes or input(f"{prompt} [y/N] ").strip().lower() == "y"


def _save_backup(prefix: str, data: dict) -> None:
    if data:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        out = BACKUP_DIR / f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}.json"
        out.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
        print(f"backup: {out}")


def _parse_size(s: str) -> int:
    m = re.fullmatch(r"(?i)\s*([\d.]+)\s*(b|kb|mb|gb)?\s*", s)
    if not m:
        raise argparse.ArgumentTypeError(f"bad size: {s}")
    return int(float(m.group(1)) * {"b": 1, "kb": 1024, "mb": 1024 ** 2, "gb": 1024 ** 3}[(m.group(2) or "b").lower()])


# ---- cleaner -------------------------------------------------------------------

def _select(rs, ids, use_all):
    if ids:
        wanted = [i.strip() for i in ids.split(",") if i.strip()]
        bad = [w for w in wanted if w not in rs.by_id()]
        if bad:
            sys.exit(f"unknown rule id(s): {', '.join(bad)}  (see: python -m woofcleaner list)")
        return wanted
    return [r.id for r in rs.rules if use_all or r.default]


def _print_results(results, mode, verbose):
    tf = tb = 0
    for r in results:
        if not r.applicable:
            continue
        tf, tb = tf + r.files, tb + r.bytes
        line = f"  {r.name:<42} {r.files:>7} files  {human(r.bytes):>10}"
        if r.reg_items:
            line += f"  {r.reg_items} reg"
        if r.skipped_locked:
            line += f"  ({r.skipped_locked} in use/skipped)"
        print(line)
        for n in r.notes:
            print(f"      note: {n}")
        if verbose:
            for p, s in r.items[:25]:
                print(f"      {human(s):>9}  {p}")
            for e in r.errors[:5]:
                print(f"      error: {e}")
    print(f"\n{'Would free' if mode == Mode.ANALYSE else 'Freed'}: {human(tb)} in {tf} files")


def cmd_list(a):
    rs = load_rules(a.rules_file)
    ctx = Context(rs)
    for r in rs.rules:
        adm = " [admin]" if r.needs_admin and not winutil.is_admin() else ""
        print(f"[{'x' if r.default else ' '}] {r.id:<28} {r.group:<12} {r.name}{adm}"
              f"{'' if is_applicable(r, ctx) else '  (not installed)'}")


def cmd_clean(a):
    rs = load_rules(a.rules_file)
    ids = _select(rs, a.rules, a.all)
    mode = Mode.CLEAN if a.command == "clean" else Mode.ANALYSE
    progress = (lambda m: None) if a.json else (lambda m: print(m, file=sys.stderr))
    ctx = Context(rs, mode=Mode.ANALYSE, progress=progress)
    if mode == Mode.CLEAN:
        print("Analysing first ...", file=sys.stderr)
        _print_results(run(ids, ctx), Mode.ANALYSE, False)
        if not _ask("\nDelete the files above?", a.yes):
            return 1
        ctx = Context(rs, mode=Mode.CLEAN, backup_dir=BACKUP_DIR, progress=progress)
    results = run(ids, ctx)
    if a.json:
        print(json.dumps([r.__dict__ for r in results], indent=1, default=list))
    else:
        print()
        _print_results(results, mode, a.verbose)


# ---- uninstaller -----------------------------------------------------------------

def cmd_programs(a):
    from . import uninstaller as un
    progs = un.list_programs(a.system)
    if a.search:
        progs = [p for p in progs if a.search.lower() in (p.name + p.publisher).lower()]
    for p in progs:
        size = human(p.size_kb * 1024) if p.size_kb else ""
        print(f"{p.name[:48]:<48} {p.version[:16]:<16} {size:>9}  {p.publisher[:30]}")
    print(f"\n{len(progs)} programs")


def cmd_uninstall(a):
    from . import uninstaller as un
    progs = un.list_programs(True)
    exact = [p for p in progs if p.name.lower() == a.name.lower()]
    hits = exact or [p for p in progs if a.name.lower() in p.name.lower()]
    if len(hits) != 1:
        print("\n".join(f"  {p.name}" for p in hits) or "no match")
        sys.exit("be more specific" if hits else 1)
    p = hits[0]
    exe, args = un.uninstall_command(p, a.quiet)
    print(f"{p.name} {p.version}\n  -> {exe} {args}")
    if not _ask("Run the uninstaller?", a.yes):
        return 1
    print(f"exit code: {un.run_uninstaller(p, a.quiet)}")
    if un.is_still_installed(p):
        input("Still registered. If the uninstaller is still open, finish it and press Enter ...")
    leftovers = un.find_leftovers(p)
    if not leftovers:
        print("No leftovers found." if not un.is_still_installed(p) else "Program is still installed.")
        return 0
    for lo in leftovers:
        print(f"  [{lo.kind}] {lo.path}  {human(lo.size) if lo.size else ''}")
    if _ask("Remove these leftovers (folders go to the Recycle Bin)?", a.yes):
        backup: dict = {}
        for e in un.remove_leftovers(leftovers, backup):
            print("  error:", e)
        _save_backup("leftovers", backup)


# ---- startup ---------------------------------------------------------------------

def cmd_startup(a):
    from . import startup as st
    items = st.list_items(include_tasks=a.tasks)
    for n, it in enumerate(items, 1):
        print(f"{n:>3}. [{'on ' if it.enabled else 'off'}] {it.name[:32]:<32} {it.source[:26]:<26} {it.command[:70]}")
    target = a.disable or a.enable or a.delete
    if not target:
        return
    it = items[target - 1]
    if a.delete:
        if _ask(f"Delete startup entry '{it.name}'?", a.yes):
            backup: dict = {}
            st.delete(it, backup)
            _save_backup("startup", backup)
    else:
        st.set_enabled(it, bool(a.enable))
        print(f"{it.name}: {'enabled' if a.enable else 'disabled'}")


# ---- duplicates ------------------------------------------------------------------

def cmd_dupes(a):
    from . import duplicates as dup
    exts = {e if e.startswith(".") else "." + e for e in a.ext.lower().split(",")} if a.ext else None
    groups = dup.find_duplicates(a.paths, a.min_size, a.hidden, exts, lambda m: print(m, file=sys.stderr))
    for g in groups[: a.limit]:
        print(f"\n{len(g.files)} x {human(g.size)}  (wasted {human(g.wasted)})")
        for f in g.files:
            print(f"   {f.path}")
    print(f"\n{len(groups)} groups, {human(sum(g.wasted for g in groups))} reclaimable")
    if a.delete:
        victims = dup.auto_select(groups, a.delete)
        if victims and _ask(f"Move {len(victims)} duplicates to the Recycle Bin (keeping the {a.delete} copy)?", a.yes):
            for i in range(0, len(victims), 200):
                winutil.send_to_recycle_bin(victims[i:i + 200])
            print("done")


# ---- software / drivers ------------------------------------------------------------

def cmd_updates(a):
    from . import updater
    ups = updater.list_upgrades(a.include_unknown)
    for u in ups:
        print(f"{u.name[:44]:<44} {u.id[:36]:<36} {u.version[:16]:>16} -> {u.available}")
    print(f"\n{len(ups)} updates available")
    ids = [u.id for u in ups] if a.all else (a.install or [])
    if ids and _ask(f"Install {len(ids)} update(s)?", a.yes):
        for pid in ids:
            print(f"--- {pid}")
            print(f"exit code {updater.upgrade(pid, print)}")


def cmd_drivers(a):
    from . import drivers as drv
    probs = drv.problem_devices()
    for p in probs:
        print(f"PROBLEM  {p.device}: {p.problem}")
    if a.list:
        for d in drv.installed_drivers():
            print(f"{d.cls[:14]:<14} {d.device[:50]:<50} {d.version:<18} {d.date}  {d.provider}")
    if not (a.scan or a.install):
        print("\nUse --scan to check Windows Update for driver updates.")
        return
    print("Searching Windows Update for drivers ...", file=sys.stderr)
    ups = drv.search_updates()
    for n, u in enumerate(ups, 1):
        print(f"{n:>3}. {u.title}  [{u.cls}, {u.date}, {u.size_mb} MB]")
    print(f"\n{len(ups)} driver update(s)")
    if a.install and ups and _ask("Install all of them (UAC prompt)?", a.yes):
        for r in drv.install_updates([u.update_id for u in ups]):
            print(r)


def cmd_update(a):
    from . import selfupdate
    rel = selfupdate.check()
    if rel is None:
        print(f"Woof Cleaner {__version__} is up to date.")
        return 0
    print(f"New version {rel.version} (you have {__version__})\n{rel.page}\n\n{rel.notes.strip()}\n")
    kind = selfupdate.install_kind()
    asset = rel.setup if kind == "installed" else rel.portable if kind == "portable" else None
    if a.check or asset is None:
        if asset is None:
            print("Running from source: use git pull." if kind == "source" else "No matching download in this release.")
        return 0
    if not _ask("Download and install it now?", a.yes):
        return 1
    f = selfupdate.download(asset, lambda d, t: print(f"\r{human(d)} / {human(t)}", end="", file=sys.stderr))
    print("\nverified SHA-256, starting the update ...")
    selfupdate.apply(rel, f)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="woofcleaner", description=f"Woof Cleaner {__version__}")
    ap.add_argument("--rules-file", default=str(DEFAULT_RULES))
    sub = ap.add_subparsers(dest="command")
    sub.add_parser("gui", help="open the window (default)")
    sub.add_parser("list", help="list cleaning rules")
    for name in ("analyze", "clean"):
        p = sub.add_parser(name, help=f"{name} junk files")
        p.add_argument("--rules", help="comma separated rule IDs (default: default rules)")
        p.add_argument("--all", action="store_true")
        p.add_argument("--yes", action="store_true")
        p.add_argument("-v", "--verbose", action="store_true")
        p.add_argument("--json", action="store_true")
    p = sub.add_parser("programs", help="list installed programs")
    p.add_argument("--search")
    p.add_argument("--system", action="store_true", help="include system components and updates")
    p = sub.add_parser("uninstall", help="uninstall a program and remove leftovers")
    p.add_argument("name")
    p.add_argument("--quiet", action="store_true", help="use the silent uninstaller when available")
    p.add_argument("--yes", action="store_true")
    p = sub.add_parser("startup", help="list / toggle startup entries")
    p.add_argument("--tasks", action="store_true", help="include logon/boot scheduled tasks")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--disable", type=int, metavar="N")
    g.add_argument("--enable", type=int, metavar="N")
    g.add_argument("--delete", type=int, metavar="N")
    p.add_argument("--yes", action="store_true")
    p = sub.add_parser("dupes", help="find duplicate files")
    p.add_argument("paths", nargs="+")
    p.add_argument("--min-size", type=_parse_size, default=_parse_size("1MB"))
    p.add_argument("--ext", help="comma separated extensions, e.g. jpg,png")
    p.add_argument("--hidden", action="store_true")
    p.add_argument("--limit", type=int, default=50, help="groups to print")
    p.add_argument("--delete", choices=["oldest", "newest", "shortest"], help="recycle extras, keeping this copy")
    p.add_argument("--yes", action="store_true")
    p = sub.add_parser("updates", help="software updates via winget")
    p.add_argument("--install", nargs="+", metavar="ID")
    p.add_argument("--all", action="store_true")
    p.add_argument("--include-unknown", action="store_true")
    p.add_argument("--yes", action="store_true")
    p = sub.add_parser("drivers", help="driver problems and Windows Update driver updates")
    p.add_argument("--list", action="store_true", help="list installed drivers")
    p.add_argument("--scan", action="store_true")
    p.add_argument("--install", action="store_true")
    p.add_argument("--yes", action="store_true")
    p = sub.add_parser("update", help="update Woof Cleaner itself from GitHub Releases")
    p.add_argument("--check", action="store_true", help="only report whether a new version exists")
    p.add_argument("--yes", action="store_true")
    a = ap.parse_args(argv)

    if a.command in (None, "gui"):
        from .gui import launch
        launch(a.rules_file)
        return 0
    handler = {"list": cmd_list, "analyze": cmd_clean, "clean": cmd_clean, "programs": cmd_programs,
               "uninstall": cmd_uninstall, "startup": cmd_startup, "dupes": cmd_dupes,
               "updates": cmd_updates, "drivers": cmd_drivers, "update": cmd_update}[a.command]
    return handler(a) or 0
