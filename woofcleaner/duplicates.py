"""Duplicate file finder: size -> 64 KB head hash -> full hash (BLAKE2b)."""
from __future__ import annotations

import hashlib
import os
import stat
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Iterable

HEAD = 64 * 1024
CHUNK = 1024 * 1024
SKIP_DIRS = {"$recycle.bin", "system volume information", "windows", "$windows.~bt", "$windows.~ws",
             "windowsapps", "winsxs", "node_modules", ".git"}


@dataclass
class DupFile:
    path: str
    mtime: float


@dataclass
class DupGroup:
    size: int
    digest: str
    files: list[DupFile] = field(default_factory=list)

    @property
    def wasted(self) -> int:
        return self.size * (len(self.files) - 1)


def _hash(path: str, limit: int | None) -> str | None:
    h = hashlib.blake2b(digest_size=20)
    try:
        with open(path, "rb") as f:
            if limit:
                h.update(f.read(limit))
            else:
                for chunk in iter(lambda: f.read(CHUNK), b""):
                    h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def _walk(roots: Iterable[str], include_hidden: bool, cancel: threading.Event):
    for root in roots:
        stack = [root]
        while stack and not cancel.is_set():
            d = stack.pop()
            try:
                it = os.scandir(d)
            except OSError:
                continue
            with it:
                for e in it:
                    try:
                        st = e.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    attrs = getattr(st, "st_file_attributes", 0)
                    # reparse point (symlink/junction) or cloud placeholder that reading would download
                    if attrs & (0x400 | 0x40000 | 0x400000):
                        continue
                    if not include_hidden and attrs & (0x2 | 0x4):  # hidden | system
                        continue
                    if stat.S_ISDIR(st.st_mode):
                        if e.name.lower() not in SKIP_DIRS:
                            stack.append(e.path)
                    elif stat.S_ISREG(st.st_mode):
                        yield e.path, st


def find_duplicates(
    roots: Iterable[str],
    min_size: int = 1,
    include_hidden: bool = False,
    extensions: set[str] | None = None,
    progress: Callable[[str], None] = lambda m: None,
    cancel: threading.Event | None = None,
) -> list[DupGroup]:
    cancel = cancel or threading.Event()
    by_size: dict[int, list[DupFile]] = defaultdict(list)
    seen: set[str] = set()
    n = 0
    for path, st in _walk(roots, include_hidden, cancel):
        if st.st_size < min_size:
            continue
        if extensions and os.path.splitext(path)[1].lower() not in extensions:
            continue
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:  # overlapping roots
            continue
        seen.add(key)
        by_size[st.st_size].append(DupFile(path, st.st_mtime))
        n += 1
        if n % 2000 == 0:
            progress(f"scanned {n} files")
    progress(f"scanned {n} files, comparing contents ...")

    groups: list[DupGroup] = []
    candidates = [(s, fs) for s, fs in by_size.items() if len(fs) > 1]
    for i, (size, files) in enumerate(candidates, 1):
        if cancel.is_set():
            break
        if i % 200 == 0:
            progress(f"comparing {i}/{len(candidates)} size groups")
        by_head: dict[str, list[DupFile]] = defaultdict(list)
        for f in files:
            d = _hash(f.path, HEAD)
            if d:
                by_head[d].append(f)
        for head, same_head in by_head.items():
            if len(same_head) < 2:
                continue
            if size <= HEAD:
                groups.append(DupGroup(size, head, same_head))
                continue
            by_full: dict[str, list[DupFile]] = defaultdict(list)
            for f in same_head:
                d = _hash(f.path, None)
                if d:
                    by_full[d].append(f)
            groups += [DupGroup(size, d, fs) for d, fs in by_full.items() if len(fs) > 1]
    groups.sort(key=lambda g: g.wasted, reverse=True)
    return groups


def auto_select(groups: list[DupGroup], keep: str = "oldest") -> list[str]:
    """Paths to delete so exactly one file per group survives. keep: oldest|newest|shortest"""
    out = []
    for g in groups:
        if keep == "newest":
            keeper = max(g.files, key=lambda f: f.mtime)
        elif keep == "shortest":
            keeper = min(g.files, key=lambda f: (len(f.path), f.path))
        else:
            keeper = min(g.files, key=lambda f: f.mtime)
        out += [f.path for f in g.files if f is not keeper]
    return out


def check_selection(groups: list[DupGroup], selected: set[str]) -> list[DupGroup]:
    """Groups where every copy is selected - deleting them would lose the data."""
    norm = {os.path.normcase(p) for p in selected}
    return [g for g in groups if all(os.path.normcase(f.path) in norm for f in g.files)]
