"""Startup Manager page: startup apps & tasks, Windows services, context-menu entries."""
from __future__ import annotations

import json
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from .. import contextmenu as cm
from .. import services as sv
from .. import startup as st
from ..paths import BACKUP_DIR
from .common import BaseTab, Table, confirm, heading, toolbar


class StartupPage(BaseTab):
    title = "Startup Manager"
    icon = ""

    def __init__(self, parent, app):
        super().__init__(parent, app)
        heading(self, "Startup Manager", "Choose what starts with Windows, which background services run, and "
                "what shows up when you right-click. Disabling is reversible.").pack(fill="x", pady=(0, 14))
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)
        self.subs = [StartupAppsTab(self.nb, app), ServicesTab(self.nb, app), ContextMenuTab(self.nb, app)]
        for s in self.subs:
            self.nb.add(s, text=s.title)
        self._shown: set[int] = set()
        self.nb.bind("<<NotebookTabChanged>>", lambda _e: self._sub_changed())

    def on_show(self):
        self._sub_changed()

    def _sub_changed(self):
        if self.app.current < 0 or self.app.pages[self.app.current] is not self:
            return
        i = self.nb.index(self.nb.select())
        if i not in self._shown:
            self._shown.add(i)
            self.subs[i].on_show()


class _Sub(BaseTab):
    def __init__(self, nb, app):
        super().__init__(nb, app, padding=(0, 12, 0, 0))


def _save_backup(prefix: str, data: dict) -> None:
    if data:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        (BACKUP_DIR / f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}.json").write_text(
            json.dumps(data, indent=1, default=str), encoding="utf-8")


# ---- startup apps ------------------------------------------------------------------------------

class StartupAppsTab(_Sub):
    title = "Startup apps"

    def __init__(self, nb, app):
        super().__init__(nb, app)
        self.items: list[st.StartupItem] = []
        bar = toolbar(self, pady=(0, 10))
        self.tasks = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Include scheduled tasks", variable=self.tasks, command=self.refresh).pack(side="left")
        ttk.Button(bar, text="Delete", style="Danger.TButton", command=self.delete).pack(side="right")
        ttk.Button(bar, text="Disable", command=lambda: self.toggle(False)).pack(side="right", padx=8)
        ttk.Button(bar, text="Enable", command=lambda: self.toggle(True)).pack(side="right")
        ttk.Button(bar, text="Refresh", style="Ghost.TButton", command=self.refresh).pack(side="right", padx=8)
        self.table = Table(self, [("state", "Status", 90, "w"), ("source", "Starts from", 190, "w"),
                                  ("command", "Command", 460, "w")], tree_heading="Program")
        self.table.tree.column("#0", width=240)
        self.table.pack(fill="both", expand=True)

    def on_show(self):
        self.refresh()

    def refresh(self):
        inc = self.tasks.get()
        self.run_bg(lambda: st.list_items(include_tasks=inc), self._loaded, "Reading startup entries ...")

    def _loaded(self, items):
        self.items = items
        self.table.clear()
        for i, it in enumerate(items):
            self.table.add(iid=str(i), text=it.name, tags=() if it.enabled else ("off",),
                           values=("● Enabled" if it.enabled else "○ Disabled", it.source, it.command))
        on = sum(i.enabled for i in items)
        self.app.set_status(f"{len(items)} startup entries, {on} enabled")

    def _selected(self):
        return [self.items[int(i)] for i in self.table.tree.selection()]

    def toggle(self, enabled: bool):
        sel = self._selected()
        if not sel:
            messagebox.showinfo("Woof Cleaner", "Select one or more entries first.", parent=self)
            return
        errors = []
        for it in sel:
            try:
                st.set_enabled(it, enabled)
            except OSError as e:
                errors.append(f"{it.name}: {e}")
        if errors:
            messagebox.showwarning("Woof Cleaner", "\n".join(errors), parent=self)
        self._loaded(self.items)

    def delete(self):
        sel = self._selected()
        if not sel or not confirm(self, "Delete", "Delete these startup entries?\n\n" + "\n".join(i.name for i in sel)):
            return
        backup: dict = {}
        errors = []
        for it in sel:
            try:
                st.delete(it, backup)
            except OSError as e:
                errors.append(f"{it.name}: {e}")
        _save_backup("startup", backup)
        if errors:
            messagebox.showwarning("Woof Cleaner", "\n".join(errors), parent=self)
        self.refresh()


# ---- services ------------------------------------------------------------------------------------

class ServicesTab(_Sub):
    title = "Windows services"
    LABELS = {"Automatic": "auto", "Automatic (delayed)": "delayed-auto", "Manual": "demand", "Disabled": "disabled"}

    def __init__(self, nb, app):
        super().__init__(nb, app)
        self.items: list[sv.Service] = []
        bar = toolbar(self, pady=(0, 8))
        self.q = tk.StringVar()
        self.q.trace_add("write", lambda *_: self._fill())
        ttk.Entry(bar, textvariable=self.q, width=26).pack(side="left")
        ttk.Label(bar, text="  search", style="Muted.TLabel").pack(side="left")
        self.ms = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Show Microsoft services", variable=self.ms, command=self._fill).pack(side="left", padx=16)
        ttk.Button(bar, text="Refresh", style="Ghost.TButton", command=self.refresh).pack(side="right")
        bar2 = toolbar(self, pady=(0, 10))
        ttk.Label(bar2, text="Selected services:", style="Muted.TLabel").pack(side="left")
        ttk.Button(bar2, text="Start", command=lambda: self.control("start")).pack(side="left", padx=(8, 0))
        ttk.Button(bar2, text="Stop", command=lambda: self.control("stop")).pack(side="left", padx=8)
        ttk.Button(bar2, text="Apply", style="Accent.TButton", command=self.apply).pack(side="right")
        self.mode = tk.StringVar(value="Manual")
        ttk.Combobox(bar2, textvariable=self.mode, values=list(self.LABELS), state="readonly", width=19).pack(side="right", padx=8)
        ttk.Label(bar2, text="Startup type", style="Muted.TLabel").pack(side="right")
        ttk.Label(self, text="Changing a service asks for administrator permission once. Previous startup types are "
                  "saved to the backup folder.", style="Muted.TLabel").pack(side="bottom", anchor="w", pady=(8, 0))
        self.table = Table(self, [("state", "Status", 90, "w"), ("start", "Startup type", 150, "w"),
                                  ("name", "Service name", 170, "w"), ("desc", "Description", 420, "w")],
                           tree_heading="Service")
        self.table.tree.column("#0", width=260)
        self.table.pack(fill="both", expand=True)

    def on_show(self):
        self.refresh()

    def refresh(self):
        self.run_bg(sv.list_services, self._loaded, "Reading Windows services ...")

    def _loaded(self, items):
        self.items = items
        self._fill()

    def _fill(self):
        q = self.q.get().lower().strip()
        self.table.clear()
        shown = 0
        for i, s in enumerate(self.items):
            if not self.ms.get() and s.is_microsoft:
                continue
            if q and q not in (s.display + s.name + s.description).lower():
                continue
            shown += 1
            tag = ("off",) if s.start_mode == "Disabled" else ()
            self.table.add(iid=str(i), text=s.display, tags=tag,
                           values=(s.state, s.start_label, s.name, s.description.replace("\n", " ")))
        self.app.set_status(f"{shown} services shown ({len(self.items)} total)")

    def _selected(self):
        return [self.items[int(i)] for i in self.table.tree.selection()]

    def _check(self, sel, action: str) -> bool:
        if not sel:
            messagebox.showinfo("Woof Cleaner", "Select one or more services first.", parent=self)
            return False
        warn = "\n\nWARNING: some of these are Microsoft services. Changing them can break Windows features." \
            if any(s.is_microsoft for s in sel) else ""
        return confirm(self, "Windows services", f"{action}:\n\n" + "\n".join(s.display for s in sel[:12]) + warn)

    def apply(self):
        sel = self._selected()
        mode = self.LABELS[self.mode.get()]
        if self._check(sel, f"Set startup type to {self.mode.get()}"):
            self.run_bg(lambda: sv.set_start_type(sel, mode, BACKUP_DIR), self._done, "Changing services ...")

    def control(self, verb: str):
        sel = self._selected()
        if self._check(sel, verb.capitalize()):
            self.run_bg(lambda: sv.control(sel, verb), self._done, f"{verb.capitalize()}ing services ...")

    def _done(self, errors):
        if errors:
            messagebox.showwarning("Woof Cleaner", "\n".join(errors[:12]), parent=self)
        self.refresh()


# ---- context menu ---------------------------------------------------------------------------------

class ContextMenuTab(_Sub):
    title = "Context menu"

    def __init__(self, nb, app):
        super().__init__(nb, app)
        self.items: list[cm.MenuEntry] = []
        bar = toolbar(self, pady=(0, 10))
        self.win = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Show Windows entries", variable=self.win, command=self._fill).pack(side="left")
        ttk.Button(bar, text="Restart Explorer", style="Ghost.TButton", command=self.restart).pack(side="left", padx=12)
        ttk.Button(bar, text="Delete", style="Danger.TButton", command=self.delete).pack(side="right")
        ttk.Button(bar, text="Disable", command=lambda: self.toggle(False)).pack(side="right", padx=8)
        ttk.Button(bar, text="Enable", command=lambda: self.toggle(True)).pack(side="right")
        ttk.Label(self, text="On Windows 11 these entries are under \"Show more options\". Changes appear after "
                  "Explorer restarts.", style="Muted.TLabel").pack(side="bottom", anchor="w", pady=(8, 0))
        self.table = Table(self, [("state", "Status", 90, "w"), ("target", "Shows on", 140, "w"),
                                  ("kind", "Type", 120, "w"), ("scope", "For", 90, "w"),
                                  ("prog", "Program", 360, "w")], tree_heading="Entry")
        self.table.tree.column("#0", width=230)
        self.table.pack(fill="both", expand=True)

    def on_show(self):
        self.refresh()

    def refresh(self):
        self.run_bg(cm.list_entries, self._loaded, "Reading context menu entries ...")

    def _loaded(self, items):
        self.items = items
        self._fill()

    def _fill(self):
        self.table.clear()
        for i, e in enumerate(self.items):
            if e.is_windows and not self.win.get():
                continue
            self.table.add(iid=str(i), text=e.name, tags=() if e.enabled else ("off",),
                           values=("● Enabled" if e.enabled else "○ Disabled", e.target,
                                   "Shell extension" if e.kind == "handler" else "Command", e.scope, e.program))
        self.app.set_status(f"{len(self.table.tree.get_children())} context menu entries")

    def _selected(self):
        return [self.items[int(i)] for i in self.table.tree.selection()]

    def toggle(self, enabled: bool):
        sel = self._selected()
        if not sel:
            messagebox.showinfo("Woof Cleaner", "Select one or more entries first.", parent=self)
            return
        errors = []
        for e in sel:
            try:
                cm.set_enabled(e, enabled)
            except OSError as ex:
                errors.append(f"{e.name}: {ex}")
        if errors:
            messagebox.showwarning("Woof Cleaner", "\n".join(errors), parent=self)
        self.refresh()
        self.app.set_status("Changed. Restart Explorer to see the new menu.")

    def delete(self):
        sel = self._selected()
        if not sel or not confirm(self, "Delete", "Remove these context menu entries from the registry?\n\n"
                                  + "\n".join(f"{e.name} ({e.target})" for e in sel) +
                                  "\n\nA registry backup is written first (restore it from the Registry page)."):
            return
        n, errors, _backup = cm.delete(sel, BACKUP_DIR)
        if errors:
            messagebox.showwarning("Woof Cleaner", "\n".join(errors), parent=self)
        self.refresh()

    def restart(self):
        if confirm(self, "Restart Explorer", "Restart Windows Explorer now? The taskbar and open folder windows "
                   "will close and come back."):
            cm.restart_explorer()
