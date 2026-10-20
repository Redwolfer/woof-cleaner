"""Duplicate Finder tab."""
from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import duplicates as dup
from .. import winutil
from ..engine import human
from .common import OFF, ON, BaseTab, Table, confirm, heading

SIZES = {"any size": 1, "> 100 KB": 100 * 1024, "> 1 MB": 1024 ** 2, "> 10 MB": 10 * 1024 ** 2, "> 100 MB": 100 * 1024 ** 2}
TYPES = {"All files": None,
         "Pictures": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".heic", ".webp", ".tif", ".tiff", ".raw"},
         "Music": {".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".wma"},
         "Videos": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm"},
         "Documents": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".odt"},
         "Archives & installers": {".zip", ".rar", ".7z", ".iso", ".exe", ".msi"}}


class DupesTab(BaseTab):
    title = "\U0001F46F Duplicate Finder"

    def __init__(self, nb, app):
        super().__init__(nb, app)
        self.groups: list[dup.DupGroup] = []
        self.marked: set[str] = set()
        self.cancel = threading.Event()
        heading(self, "Duplicate Finder", "Finds files with identical content (size, then BLAKE2 hash). "
                "Deleted copies go to the Recycle Bin, and at least one copy of every file is always kept.").pack(fill="x", pady=(0, 8))
        opts = ttk.Frame(self)
        opts.pack(fill="x")
        ttk.Label(opts, text="Folder:").pack(side="left")
        self.folder = tk.StringVar(value=os.path.expanduser("~"))
        ttk.Entry(opts, textvariable=self.folder, width=48).pack(side="left", padx=4)
        ttk.Button(opts, text="Browse ...", command=self._browse).pack(side="left")
        ttk.Label(opts, text="  Size:").pack(side="left")
        self.size = tk.StringVar(value="> 1 MB")
        ttk.Combobox(opts, textvariable=self.size, values=list(SIZES), width=10, state="readonly").pack(side="left")
        ttk.Label(opts, text="  Type:").pack(side="left")
        self.kind = tk.StringVar(value="All files")
        ttk.Combobox(opts, textvariable=self.kind, values=list(TYPES), width=18, state="readonly").pack(side="left")
        self.hidden = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="Hidden/system", variable=self.hidden).pack(side="left", padx=6)

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(6, 0))
        ttk.Button(bar, text="Search", style="Accent.TButton", command=self.search).pack(side="left")
        ttk.Button(bar, text="Stop", command=self.cancel.set).pack(side="left", padx=6)
        ttk.Label(bar, text="  Auto-select, keep:").pack(side="left")
        for label, key in (("oldest", "oldest"), ("newest", "newest"), ("shortest path", "shortest")):
            ttk.Button(bar, text=label, command=lambda k=key: self._auto(k)).pack(side="left", padx=2)
        ttk.Button(bar, text="Clear marks", command=lambda: self._set_marks(set())).pack(side="left", padx=6)
        ttk.Button(bar, text="Delete marked", command=self.delete).pack(side="right")

        self.table = Table(self, [("size", "Size", 90, "e"), ("modified", "Modified", 140, "w")], tree_heading="File")
        self.table.pack(fill="both", expand=True, pady=6)
        self.table.tree.bind("<Button-1>", self._toggle)
        self.table.tree.bind("<Double-1>", self._open_folder)
        self.summary = ttk.Label(self, text="", style="Big.TLabel")
        self.summary.pack(anchor="w")

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
        self.marked = set()
        self._render()
        wasted = sum(g.wasted for g in groups)
        self.app.set_status(("Stopped - partial results. " if self.cancel.is_set() else "") +
                            f"{len(groups)} duplicate groups, {human(wasted)} reclaimable")

    def _render(self):
        from datetime import datetime
        t = self.table.tree
        self.table.clear()
        for gi, g in enumerate(self.groups[:3000]):
            node = t.insert("", "end", iid=f"g{gi}", open=True,
                            text=f"{len(g.files)} copies  •  {human(g.wasted)} wasted",
                            values=(human(g.size), ""))
            for fi, f in enumerate(g.files):
                mark = ON if f.path in self.marked else OFF
                t.insert(node, "end", iid=f"g{gi}f{fi}", text=f"{mark}  {f.path}",
                         values=(human(g.size), datetime.fromtimestamp(f.mtime).strftime("%Y-%m-%d %H:%M")))
        marked_bytes = sum(g.size for g in self.groups for f in g.files if f.path in self.marked)
        self.summary.config(text=f"{len(self.marked)} files marked ({human(marked_bytes)})" if self.groups else "")

    def _path_of(self, iid: str) -> str | None:
        if "f" not in iid:
            return None
        gi, fi = iid[1:].split("f")
        return self.groups[int(gi)].files[int(fi)].path

    def _toggle(self, ev):
        iid = self.table.tree.identify_row(ev.y)
        path = self._path_of(iid) if iid else None
        if not path or self.table.tree.identify_region(ev.x, ev.y) != "tree":
            return
        self.marked ^= {path}
        t = self.table.tree.item(iid, "text")
        self.table.tree.item(iid, text=(ON if path in self.marked else OFF) + t[1:])
        self._render_summary()
        return "break"

    def _render_summary(self):
        marked_bytes = sum(g.size for g in self.groups for f in g.files if f.path in self.marked)
        self.summary.config(text=f"{len(self.marked)} files marked ({human(marked_bytes)})")

    def _set_marks(self, marks):
        self.marked = set(marks)
        self._render()

    def _auto(self, keep):
        self._set_marks(dup.auto_select(self.groups, keep))

    def _open_folder(self, ev):
        iid = self.table.tree.identify_row(ev.y)
        path = self._path_of(iid) if iid else None
        if path:
            winutil.shell_execute("explorer.exe", f'/select,"{path}"', wait=False)

    def delete(self):
        if not self.marked:
            return
        lost = dup.check_selection(self.groups, self.marked)
        if lost:
            messagebox.showerror("Woof Cleaner", f"{len(lost)} group(s) have every copy marked. Unmark at least one "
                                 "copy in each group.", parent=self)
            return
        n = len(self.marked)
        if not confirm(self, "Delete duplicates", f"Move {n} duplicate file(s) to the Recycle Bin?"):
            return
        paths = sorted(self.marked)

        def work():
            for i in range(0, len(paths), 200):
                winutil.send_to_recycle_bin(paths[i:i + 200])
            return len(paths)

        def done(count):
            gone = set(paths)
            for g in self.groups:
                g.files = [f for f in g.files if f.path not in gone]
            self.groups = [g for g in self.groups if len(g.files) > 1]
            self._set_marks(set())
            self.app.set_status(f"Moved {count} files to the Recycle Bin")

        self.run_bg(work, done, "Deleting ...")
