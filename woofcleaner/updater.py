"""Software updater backed by winget (Windows Package Manager)."""
from __future__ import annotations

import re
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass
from typing import Callable

_SPINNER = re.compile(r"^\s*[-\\|/]?\s*$")  # a lone spinner glyph (not the table's dashed rule)
_BAR = re.compile(r"[▀-▟]")


@dataclass
class Upgrade:
    name: str
    id: str
    version: str
    available: str
    source: str = ""


def winget_path() -> str | None:
    return shutil.which("winget")


def _run(args: list[str], timeout: int = 300) -> str:
    exe = winget_path()
    if not exe:
        raise RuntimeError("winget is not installed (get 'App Installer' from the Microsoft Store)")
    r = subprocess.run([exe, *args], capture_output=True, timeout=timeout, creationflags=0x08000000)
    return r.stdout.decode("utf-8", "replace")


def _clean_lines(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = raw.split("\r")[-1].rstrip()   # keep only the last redraw of a progress line
        if not line or _SPINNER.match(line) or _BAR.search(line):
            continue
        lines.append(line)
    return lines


def _w(ch: str) -> int:
    """Terminal cell width: CJK/fullwidth characters take two columns in winget's table."""
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in "WF" else 1


def _dwidth(s: str) -> int:
    return sum(_w(c) for c in s)


def _occupied(line: str) -> set[int]:
    pos, occ = 0, set()
    for ch in line:
        if ch != " ":
            occ.add(pos)
        pos += _w(ch)
    return occ


def _columns(header: str, rows: list[str]) -> list[int]:
    """Display-column start of each table column. The order is fixed (Name, Id, Version, Available[, Source]);
    titles are localised and may contain spaces, so fall back to wider gaps or to the data rows."""
    starts, gaps, pos, run, prev = [], [], 0, 0, " "
    for ch in header:
        if ch != " " and prev == " ":
            starts.append(pos)
            gaps.append(run)
        run = run + 1 if ch == " " else 0
        prev = ch
        pos += _w(ch)
    if len(starts) in (4, 5):
        return starts
    wide = [s for s, g in zip(starts, gaps) if s == 0 or g >= 2]
    if len(wide) in (4, 5):
        return wide
    occ = [_occupied(r) for r in rows]
    blank_before = [s for s in starts if s == 0 or all(s - 1 not in o for o in occ)]
    return blank_before if len(blank_before) in (4, 5) else starts


def _cells(line: str, cols: list[int]) -> list[str]:
    out = [""] * len(cols)
    pos = idx = 0
    for ch in line:
        while idx + 1 < len(cols) and pos >= cols[idx + 1]:
            idx += 1
        out[idx] += ch
        pos += _w(ch)
    return [c.strip() for c in out]


def parse_table(text: str) -> list[Upgrade]:
    """Parse winget's fixed-width table(s). A dashed rule follows each header line."""
    lines = _clean_lines(text)
    out: list[Upgrade] = []
    rules = [i for i, l in enumerate(lines) if re.fullmatch(r"-{10,}", l.strip()) and i > 0]
    for n, r in enumerate(rules):
        end = rules[n + 1] - 1 if n + 1 < len(rules) else len(lines)
        rows = [l for l in lines[r + 1:end] if l.strip()]
        cols = _columns(lines[r - 1], rows)
        if len(cols) < 4:
            continue
        for line in rows:
            if _dwidth(line) <= cols[3]:
                continue  # footer such as "26 upgrades available." or a sentence
            cells = _cells(line, cols)
            name, pid, ver, avail = cells[:4]
            if not pid or " " in pid or not avail:
                continue
            out.append(Upgrade(name.rstrip("… "), pid, ver, avail, cells[4] if len(cells) > 4 else ""))
    return out


def list_upgrades(include_unknown: bool = False) -> list[Upgrade]:
    args = ["upgrade", "--accept-source-agreements", "--disable-interactivity"]
    if include_unknown:
        args.append("--include-unknown")
    return parse_table(_run(args))


def upgrade(pkg_id: str, on_line: Callable[[str], None] = lambda s: None) -> int:
    """Install the newest version silently. Installers that need admin trigger their own UAC prompt."""
    exe = winget_path()
    if not exe:
        raise RuntimeError("winget is not installed")
    p = subprocess.Popen(
        [exe, "upgrade", "--id", pkg_id, "--exact", "--silent", "--accept-source-agreements",
         "--accept-package-agreements", "--disable-interactivity"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=0x08000000,
    )
    buf = b""
    while True:
        ch = p.stdout.read(1)
        if not ch:
            break
        if ch in b"\r\n":
            line = buf.decode("utf-8", "replace").strip()
            if line and not _SPINNER.match(line) and not _BAR.search(line):
                on_line(line)
            buf = b""
        else:
            buf += ch
    return p.wait()
