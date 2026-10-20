"""Duplicate Finder page."""
from __future__ import annotations

import os
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from .. import duplicates as dup
from .. import winutil
from ..engine import human
from .common import BaseTab, Table, confirm, heading, stat_row, toolbar

SIZES = {"any size": 1, "> 100 KB": 100 * 1024, "> 1 MB": 1024 ** 2, "> 10 MB": 10 * 1024 ** 2, "> 100 MB": 100 * 1024 ** 2}
TYPES = {"All files": None,
         "Pictures": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".heic", ".webp", ".tif", ".tiff", ".raw"},
         "Music": {".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".wma"},
         "Videos": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm"},
         "Documents": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".odt"},
         "Archives & installers": {".zip", ".rar", ".7z", ".iso", ".exe", ".msi"}}


class DupesTab(BaseTab):
    title = "Duplicate Finder"
    icon = ""

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.groups: list[dup.DupGroup] = []
        self.cancel = threading.Event()
        head = heading(self, "Duplicate Finder", "Finds files with identical content (size, then BLAKE2 hash). "
                       "Deleted copies go to the Recycle Bin, and one copy of every file is always kept.")
        head.pack(fill="x")
        ttk.Button(head.actions, text="Move marked to Recycle Bin", style="Accent.TButton",
                   command=self.delete).pack(side="right")
        ttk.Button(head.actions, text="Search", command=self.search).pack(side="right", padx=8)

        opts = toolbar(self)
        self.folder = tk.StringVar(value=os.path.expanduser("~"))
        ttk.Entry(opts, textvariable=self.folder, width=44).pack(side="left")
        ttk.Button(opts, text="Browse ...", command=self._browse).pack(side="left", padx=6)
        ttk.Label(opts, text="Size", style="Muted.TLabel").pack(side="left", padx=(12, 4))
        self.size = tk.StringVar(value="> 1 MB")
        ttk.Combobox(opts, textvariable=self.size, values=list(SIZES), width=10, state="readonly").pack(side="left")
        ttk.Label(opts, text="Type", style="Muted.TLabel").pack(side="left", padx=(12, 4))
        self.kind = tk.StringVar(value="All files")
        ttk.Combobox(opts, textvariable=self.kind, values=list(TYPES), width=18, state="readonly").pack(side="left")
        self.hidden = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="Hidden/system", variable=self.hidden).pack(side="left", padx=12)

        bar = toolbar(self, pady=(0, 10))
        ttk.Label(bar, text="Auto-select, keep the", style="Muted.TLabel").pack(side="left")
        for label, key in (("oldest", "oldest"), ("newest", "newest"), ("shortest path", "shortest")):
            ttk.Button(bar, text=label, style="Ghost.TButton", command=lambda k=key: self._auto(k)).pack(side="left")
        ttk.Button(bar, text="Clear marks", style="Ghost.TButton", command=lambda: self.table.set_all(False)).pack(side="left", padx=8)
        ttk.Button(bar, text="Stop search", style="Danger.TButton", command=self.cancel.set).pack(side="right")
        ttk.Button(bar, text="Open file location", style="Ghost.TButton", command=self._open_folder).pack(side="right", padx=8)

        self.cards = stat_row(self, [("Reclaimable", True), ("Duplicate groups", False), ("Marked", False)])
        self.table = Table(self, [("size", "Size", 100, "e"), ("modified", "Modified", 150, "w")],
                           tree_heading="File", on_toggle=self._summary)
        self.table.pack(fill="both", expand=True)

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.folder.get(), parent=self)
        if d:
            self.folder.set(os.path.normpath(d))

    def search(self):
        root = self.folder.get()
        if not os.path.isdir(root):
            messagebox.showwarning("Woof Cleaner", "Pick an existing folder.", parent=self)
            return
        self.cancel.clear()
        min_size, exts, hidden = SIZES[self.size.get()], TYPES[self.kind.get()], self.hidden.get()
        self.run_bg(lambda: dup.find_duplicates([root], min_size, hidden, exts, self.status, self.cancel),
                    self._loaded, f"Scanning {root} ...")

    def _loaded(self, groups):
        self.groups = groups
        self._render(set())
        self.app.set_status(("Stopped - partial results. " if self.cancel.is_set() else "") +
                            f"{len(groups)} duplicate groups, {human(sum(g.wasted for g in groups))} reclaimable")

    def _render(self, marked: set[str]):
        self.table.clear()
        self.path_of: dict[str, str] = {}
        for gi, g in enumerate(self.groups[:3000]):
            node = self.table.group(iid=f"g{gi}", text=f"{len(g.files)} copies  ·  {human(g.wasted)} wasted",
                                    values=(human(g.size), ""))
            for fi, f in enumerate(g.files):
                iid = f"g{gi}f{fi}"
                self.path_of[iid] = f.path
                self.table.add(iid=iid, text=f.path, parent=node, check=f.path in marked,
                               values=(human(g.size), datetime.fromtimestamp(f.mtime).strftime("%Y-%m-%d %H:%M")))
        self._summary()

    def marked(self) -> set[str]:
        return {self.path_of[i] for i in self.table.checked() if i in self.path_of}

    def _summary(self):
        m = self.marked()
        size_of = {f.path: g.size for g in self.groups for f in g.files}
        self.cards[0].set(human(sum(g.wasted for g in self.groups)), "if one copy of each file is kept")
        self.cards[1].set(f"{len(self.groups):,}", "")
        self.cards[2].set(f"{len(m):,}", human(sum(size_of.get(p, 0) for p in m)) + " to remove" if m else "")

    def _auto(self, keep):
        self._render(set(dup.auto_select(self.groups, keep)))

    def _open_folder(self):
        sel = self.table.tree.selection()
        path = self.path_of.get(sel[0]) if sel else None
        if path:
            winutil.shell_execute("explorer.exe", f'/select,"{path}"', wait=False)

    def delete(self):
        marked = self.marked()
        if not marked:
            messagebox.showinfo("Woof Cleaner", "Tick the copies to remove (or use Auto-select).", parent=self)
            return
        lost = dup.check_selection(self.groups, marked)
        if lost:
            messagebox.showerror("Woof Cleaner", f"{len(lost)} group(s) have every copy marked. Unmark at least one "
                                 "copy in each group.", parent=self)
            return
        if not confirm(self, "Delete duplicates", f"Move {len(marked)} duplicate file(s) to the Recycle Bin?"):
            return
        paths = sorted(marked)

        def work():
            for i in range(0, len(paths), 200):
                winutil.send_to_recycle_bin(paths[i:i + 200])
            return len(paths)

        def done(count):
            gone = set(paths)
            for g in self.groups:
                g.files = [f for f in g.files if f.path not in gone]
            self.groups = [g for g in self.groups if len(g.files) > 1]
            self._render(set())
            self.app.set_status(f"Moved {count} files to the Recycle Bin")

        self.run_bg(work, done, "Deleting ...")
