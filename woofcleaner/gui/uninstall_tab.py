"""Software Uninstaller: list programs, run their uninstaller, then sweep leftovers."""
from __future__ import annotations

import json
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from .. import uninstaller as un
from ..engine import human
from ..paths import BACKUP_DIR
from .common import BaseTab, Table, confirm, heading, stat_row, toolbar


class UninstallTab(BaseTab):
    title = "Uninstaller"
    icon = ""

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.programs: list[un.Program] = []
        head = heading(self, "Software Uninstaller", "Runs each program's own uninstaller, then offers to remove "
                       "the folders and registry keys it left behind (to the Recycle Bin / with a backup).")
        head.pack(fill="x")
        ttk.Button(head.actions, text="Uninstall", style="Accent.TButton", command=self.uninstall).pack(side="right")
        bar = toolbar(self)
        self.q = tk.StringVar()
        self.q.trace_add("write", lambda *_: self._fill())
        ttk.Entry(bar, textvariable=self.q, width=34).pack(side="left")
        ttk.Label(bar, text="  search by name or publisher", style="Muted.TLabel").pack(side="left")
        self.show_sys = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Show system components", variable=self.show_sys,
                        command=self.refresh).pack(side="left", padx=16)
        ttk.Button(bar, text="Refresh", style="Ghost.TButton", command=self.refresh).pack(side="right")
        self.cards = stat_row(self, [("Programs", True), ("Reported size", False)])
        self.table = Table(self, [("publisher", "Publisher", 200, "w"), ("version", "Version", 120, "w"),
                                  ("size", "Size", 90, "e"), ("date", "Installed", 100, "w"),
                                  ("scope", "Type", 100, "w")], tree_heading="Program", selectmode="browse")
        self.table.tree.column("#0", width=340)
        self.table.pack(fill="both", expand=True)
        self.table.tree.bind("<Double-1>", lambda e: self.uninstall())

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
            self.table.add(iid=str(i), text=p.name, values=(
                p.publisher, p.version, human(p.size_kb * 1024) if p.size_kb else "",
                p.install_date, f"{p.scope} {p.arch}".strip()))
        self.cards[0].set(str(len(self.table.tree.get_children())), "shown" if q else "installed")
        self.cards[1].set(human(total), "as reported by the installers")

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
        self.geometry("820x440")
        self.transient(tab)
        tab.app.theme.paint(self, bg="bg")
        body = ttk.Frame(self, padding=(20, 16))
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Leftovers found", style="H1.TLabel").pack(anchor="w")
        ttk.Label(body, text=f"{p.name} was uninstalled. These items look like what it left behind:",
                  style="Sub.TLabel").pack(anchor="w", pady=(2, 12))
        self.table = Table(body, [("kind", "Type", 80, "w"), ("size", "Size", 80, "e"), ("why", "Found by", 120, "w")],
                           tree_heading="Path", height=10)
        self.table.pack(fill="both", expand=True)
        for i, lo in enumerate(leftovers):
            self.table.add(iid=str(i), text=lo.path, check=True,
                           values=(lo.kind, human(lo.size) if lo.kind == "folder" else "", lo.reason))
        bar = ttk.Frame(body)
        bar.pack(fill="x", pady=(12, 0))
        ttk.Button(bar, text="Remove selected", style="Accent.TButton", command=self._remove).pack(side="right")
        ttk.Button(bar, text="Keep all", command=self.destroy).pack(side="right", padx=8)
        tab.app.theme.title_bar(self)

    def _remove(self):
        chosen = [self.items[int(i)] for i in self.table.checked()]
        backup: dict = {}
        errors = un.remove_leftovers(chosen, backup)
        if backup:
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            (BACKUP_DIR / f"leftovers_{datetime.now():%Y%m%d_%H%M%S}.json").write_text(
                json.dumps(backup, indent=1, default=str), encoding="utf-8")
        msg = f"Removed {len(chosen) - len(errors)} item(s). Folders are in the Recycle Bin."
        if errors:
            msg += "\n\nErrors:\n" + "\n".join(errors[:8])
        messagebox.showinfo("Woof Cleaner", msg, parent=self)
        self.destroy()
