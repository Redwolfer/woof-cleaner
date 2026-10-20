"""Software Updater tab (winget)."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .. import updater
from .common import OFF, ON, BaseTab, Table, confirm, heading


class SoftwareTab(BaseTab):
    title = "⬆ Software Updater"

    def __init__(self, nb, app):
        super().__init__(nb, app)
        self.ups: list[updater.Upgrade] = []
        self.checked: set[str] = set()
        heading(self, "Software Updater", "Finds newer versions of your installed apps with winget "
                "(Windows Package Manager) and installs them silently from the official winget catalogue.").pack(fill="x", pady=(0, 8))
        bar = ttk.Frame(self)
        bar.pack(fill="x")
        ttk.Button(bar, text="Check for updates", command=self.refresh).pack(side="left")
        self.unknown = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Include apps with unknown version", variable=self.unknown).pack(side="left", padx=8)
        ttk.Button(bar, text="Update selected", style="Accent.TButton", command=self.update_selected).pack(side="right")
        ttk.Button(bar, text="Select all", command=lambda: self._mark_all(True)).pack(side="right", padx=6)
        self.table = Table(self, [("id", "Package Id", 240, "w"), ("ver", "Installed", 120, "w"),
                                  ("avail", "Available", 120, "w"), ("src", "Source", 70, "w")], tree_heading="Program")
        self.table.pack(fill="both", expand=True, pady=6)
        self.table.tree.bind("<Button-1>", self._toggle)
        ttk.Label(self, text="Log").pack(anchor="w")
        self.log = tk.Text(self, height=7, wrap="none", font=("Consolas", 9))
        self.log.pack(fill="x")
        if not updater.winget_path():
            self._log("winget was not found. Install 'App Installer' from the Microsoft Store to use this tool.")

    def on_show(self):
        if updater.winget_path():
            self.refresh()

    def _log(self, line: str):
        self.log.insert("end", line + "\n")
        self.log.see("end")

    def refresh(self):
        inc = self.unknown.get()
        self.run_bg(lambda: updater.list_upgrades(inc), self._loaded, "Asking winget for updates ...")

    def _loaded(self, ups):
        self.ups = ups
        self.checked = {u.id for u in ups}
        self._render()
        self.app.set_status(f"{len(ups)} updates available")

    def _render(self):
        self.table.clear()
        for u in self.ups:
            self.table.tree.insert("", "end", iid=u.id, text=f"{ON if u.id in self.checked else OFF}  {u.name}",
                                   values=(u.id, u.version, u.available, u.source))

    def _toggle(self, ev):
        iid = self.table.tree.identify_row(ev.y)
        if not iid or self.table.tree.identify_region(ev.x, ev.y) != "tree":
            return
        self.checked ^= {iid}
        self._render()
        return "break"

    def _mark_all(self, on):
        self.checked = {u.id for u in self.ups} if on else set()
        self._render()

    def update_selected(self):
        ids = [u.id for u in self.ups if u.id in self.checked]
        if not ids:
            messagebox.showinfo("Woof Cleaner", "Tick the apps to update.", parent=self)
            return
        if not confirm(self, "Update apps", f"Download and install updates for {len(ids)} app(s)?\n\n"
                       "Close those apps first. Some installers will ask for administrator permission."):
            return

        def work():
            results = {}
            for n, pid in enumerate(ids, 1):
                self.app.post(lambda p=pid, n=n: self._log(f"--- [{n}/{len(ids)}] {p}"))
                code = updater.upgrade(pid, lambda line: self.app.post(lambda l=line: self._log(l)))
                results[pid] = code
            return results

        def done(results):
            ok = [p for p, c in results.items() if c == 0]
            bad = {p: c for p, c in results.items() if c != 0}
            self._log(f"Done: {len(ok)} updated, {len(bad)} failed")
            if bad:
                messagebox.showwarning("Woof Cleaner", "Some updates failed:\n" +
                                       "\n".join(f"{p} (code {c & 0xFFFFFFFF:#x})" for p, c in bad.items()), parent=self)
            self.refresh()

        self.run_bg(work, done, "Updating apps ...")
