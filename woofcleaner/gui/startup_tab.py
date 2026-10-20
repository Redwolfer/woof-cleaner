"""Startup manager tab."""
from __future__ import annotations

import json
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from .. import startup as st
from .common import BaseTab, Table, confirm, heading


class StartupTab(BaseTab):
    title = "\U0001F680 Startup"

    def __init__(self, nb, app):
        super().__init__(nb, app)
        self.items: list[st.StartupItem] = []
        heading(self, "Startup Manager", "Programs that start when you sign in. Disabling is reversible "
                "(same switch as Task Manager); deleting removes the entry (a backup is kept).").pack(fill="x", pady=(0, 8))
        bar = ttk.Frame(self)
        bar.pack(fill="x")
        self.tasks = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Include scheduled tasks", variable=self.tasks, command=self.refresh).pack(side="left")
        ttk.Button(bar, text="Refresh", command=self.refresh).pack(side="right")
        ttk.Button(bar, text="Delete", command=self.delete).pack(side="right", padx=6)
        ttk.Button(bar, text="Disable", command=lambda: self.toggle(False)).pack(side="right")
        ttk.Button(bar, text="Enable", command=lambda: self.toggle(True)).pack(side="right", padx=6)
        self.table = Table(self, [("state", "Status", 80, "w"), ("name", "Name", 220, "w"),
                                  ("source", "Location", 190, "w"), ("command", "Command", 480, "w")])
        self.table.pack(fill="both", expand=True, pady=6)
        self.table.tree.tag_configure("off", foreground="#999")

    def on_show(self):
        self.refresh()

    def refresh(self):
        inc = self.tasks.get()
        self.run_bg(lambda: st.list_items(include_tasks=inc), self._loaded, "Reading startup entries ...")

    def _loaded(self, items):
        self.items = items
        self.table.clear()
        for i, it in enumerate(items):
            self.table.tree.insert("", "end", iid=str(i), tags=() if it.enabled else ("off",),
                                   values=("Enabled" if it.enabled else "Disabled", it.name, it.source, it.command))
        on = sum(i.enabled for i in items)
        self.app.set_status(f"{len(items)} startup entries, {on} enabled")

    def _selected(self):
        return [self.items[int(i)] for i in self.table.tree.selection()]

    def toggle(self, enabled: bool):
        sel = self._selected()
        if not sel:
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
        if backup:
            from ..cli import BACKUP_DIR
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            (BACKUP_DIR / f"startup_{datetime.now():%Y%m%d_%H%M%S}.json").write_text(json.dumps(backup, indent=1, default=str))
        if errors:
            messagebox.showwarning("Woof Cleaner", "\n".join(errors), parent=self)
        self.refresh()
