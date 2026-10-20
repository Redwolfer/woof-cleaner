"""Software Uninstaller: list programs, run their uninstaller, then sweep leftovers."""
from __future__ import annotations

import json
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from .. import uninstaller as un
from ..engine import human
from .common import OFF, ON, BaseTab, Table, confirm, heading


class UninstallTab(BaseTab):
    title = "\U0001F5D1 Uninstaller"

    def __init__(self, nb, app):
        super().__init__(nb, app)
        self.programs: list[un.Program] = []
        heading(self, "Software Uninstaller", "Runs each program's own uninstaller, then offers to remove the "
                "folders and registry keys it left behind (to the Recycle Bin / with a backup).").pack(fill="x", pady=(0, 8))
        bar = ttk.Frame(self)
        bar.pack(fill="x")
        ttk.Label(bar, text="Search:").pack(side="left")
        self.q = tk.StringVar()
        self.q.trace_add("write", lambda *_: self._fill())
        ttk.Entry(bar, textvariable=self.q, width=30).pack(side="left", padx=(4, 12))
        self.show_sys = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Show system components", variable=self.show_sys, command=self.refresh).pack(side="left")
        ttk.Button(bar, text="Refresh", command=self.refresh).pack(side="right")
        ttk.Button(bar, text="Uninstall", style="Accent.TButton", command=self.uninstall).pack(side="right", padx=6)
        self.table = Table(self, [("name", "Program", 330, "w"), ("publisher", "Publisher", 200, "w"),
                                  ("version", "Version", 110, "w"), ("size", "Size", 80, "e"),
                                  ("date", "Installed", 90, "w"), ("scope", "Type", 90, "w")], selectmode="browse")
        self.table.pack(fill="both", expand=True, pady=6)
        self.table.tree.bind("<Double-1>", lambda e: self.uninstall())
        self.summary = ttk.Label(self, text="", style="Big.TLabel")
        self.summary.pack(anchor="w")

    def on_show(self):
        self.refresh()

    def refresh(self):
        inc = self.show_sys.get()
        self.run_bg(lambda: un.list_programs(include_system=inc), self._loaded, "Reading installed programs ...")

    def _loaded(self, programs):
        self.programs = programs
        self._fill()
        self.app.set_status(f"{len(programs)} programs")

    def _fill(self):
        q = self.q.get().lower().strip()
        self.table.clear()
        total = 0
        for i, p in enumerate(self.programs):
            if q and q not in p.name.lower() and q not in p.publisher.lower():
                continue
            total += p.size_kb * 1024
            self.table.tree.insert("", "end", iid=str(i), values=(
                p.name, p.publisher, p.version, human(p.size_kb * 1024) if p.size_kb else "",
                p.install_date, f"{p.scope} {p.arch}".strip()))
        self.summary.config(text=f"{len(self.table.tree.get_children())} programs, {human(total)} reported size")

    def _selected(self) -> un.Program | None:
        sel = self.table.tree.selection()
        return self.programs[int(sel[0])] if sel else None

    def uninstall(self):
        p = self._selected()
        if not p:
            messagebox.showinfo("Woof Cleaner", "Select a program first.", parent=self)
            return
        if not p.can_uninstall:
            messagebox.showwarning("Woof Cleaner", f"{p.name} has no uninstaller registered.", parent=self)
            return
        exe, args = un.uninstall_command(p)
        if not confirm(self, "Uninstall", f"Uninstall {p.name}?\n\nThe vendor uninstaller will start:\n{exe} {args}"):
            return
        self.run_bg(lambda: (un.run_uninstaller(p), un.find_leftovers(p), un.is_still_installed(p)),
                    lambda r: self._after_uninstall(p, *r), f"Uninstalling {p.name} ...")

    def _after_uninstall(self, p, code, leftovers, still):
        self.refresh()
        if still:
            # Many uninstallers (Inno Setup, NSIS) hand off to a copy of themselves and exit immediately.
            if messagebox.askokcancel("Woof Cleaner", f"{p.name} is still registered (exit code {code}).\n\n"
                                      "If the uninstaller window is still open, finish it, then press OK to "
                                      "check again and scan for leftovers.", parent=self):
                self.run_bg(lambda: (code, un.find_leftovers(p), un.is_still_installed(p)),
                            lambda r: self._after_uninstall(p, *r), "Checking ...")
            return
        if not leftovers:
            messagebox.showinfo("Woof Cleaner", f"{p.name} was removed. No leftovers found.", parent=self)
            return
        LeftoverDialog(self, p, leftovers)


class LeftoverDialog(tk.Toplevel):
    def __init__(self, tab: UninstallTab, p, leftovers):
        super().__init__(tab)
        self.tab, self.items = tab, leftovers
        self.title(f"Leftovers of {p.name}")
        self.geometry("760x380")
        self.transient(tab)
        ttk.Label(self, text=f"{p.name} was uninstalled. These items look like leftovers:", style="H1.TLabel").pack(anchor="w", padx=10, pady=8)
        self.table = Table(self, [("kind", "Type", 80, "w"), ("size", "Size", 80, "e"), ("why", "Found by", 120, "w")],
                           tree_heading="Path", height=10)
        self.table.pack(fill="both", expand=True, padx=10)
        self.checked = {i: True for i in range(len(leftovers))}
        for i, lo in enumerate(leftovers):
            self.table.tree.insert("", "end", iid=str(i), text=f"{ON}  {lo.path}",
                                   values=(lo.kind, human(lo.size) if lo.kind == "folder" else "", lo.reason))
        self.table.tree.bind("<Button-1>", self._toggle)
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=10, pady=8)
        ttk.Button(bar, text="Remove selected", style="Accent.TButton", command=self._remove).pack(side="right")
        ttk.Button(bar, text="Keep all", command=self.destroy).pack(side="right", padx=6)

    def _toggle(self, ev):
        iid = self.table.tree.identify_row(ev.y)
        if not iid:
            return
        i = int(iid)
        self.checked[i] = not self.checked[i]
        t = self.table.tree.item(iid, "text")
        self.table.tree.item(iid, text=(ON if self.checked[i] else OFF) + t[1:])
        return "break"

    def _remove(self):
        chosen = [lo for i, lo in enumerate(self.items) if self.checked[i]]
        backup: dict = {}
        errors = un.remove_leftovers(chosen, backup)
        if backup:
            from ..cli import BACKUP_DIR
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            (BACKUP_DIR / f"leftovers_{datetime.now():%Y%m%d_%H%M%S}.json").write_text(json.dumps(backup, indent=1, default=str))
        msg = f"Removed {len(chosen) - len(errors)} item(s). Folders are in the Recycle Bin."
        if errors:
            msg += "\n\nErrors:\n" + "\n".join(errors[:8])
        messagebox.showinfo("Woof Cleaner", msg, parent=self)
        self.destroy()
