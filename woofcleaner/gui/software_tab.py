"""Software Updater page (winget), with Skip version / Ignore app and a Skipped & ignored view."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .. import updater
from .common import BaseTab, Table, confirm, heading, stat_row, text_box, toolbar


class SoftwareTab(BaseTab):
    title = "Software Updater"
    icon = ""

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.all: list[updater.Upgrade] = []
        self.active: list[updater.Upgrade] = []
        self.hidden: list[tuple[updater.Upgrade, str]] = []
        head = heading(self, "Software Updater", "Finds newer versions of your apps with winget (Windows Package "
                       "Manager) and installs them silently from the official catalogue.")
        head.pack(fill="x")
        self.btn_up = ttk.Button(head.actions, text="Update selected", style="Accent.TButton", command=self.update_selected)
        self.btn_up.pack(side="right")
        ttk.Button(head.actions, text="Check for updates", command=self.refresh).pack(side="right", padx=8)

        bar = toolbar(self)
        self.view = tk.StringVar(value="updates")
        self.rb_up = ttk.Radiobutton(bar, text="Updates", value="updates", variable=self.view, command=self._render)
        self.rb_up.pack(side="left")
        self.rb_hid = ttk.Radiobutton(bar, text="Skipped & ignored", value="hidden", variable=self.view,
                                      command=self._render)
        self.rb_hid.pack(side="left", padx=14)
        self.unknown = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Include apps with unknown version", variable=self.unknown).pack(side="left", padx=10)
        self.btn_resume = ttk.Button(bar, text="Resume updates", command=self.resume)
        self.btn_ignore = ttk.Button(bar, text="Ignore app", command=self.ignore)
        self.btn_skip = ttk.Button(bar, text="Skip this version", command=self.skip)
        for b in (self.btn_ignore, self.btn_skip):
            b.pack(side="right", padx=(8, 0))

        self.cards = stat_row(self, [("Updates available", True), ("Selected", False), ("Skipped / ignored", False)])
        # bottom area first: a table packed with expand=True would otherwise take all the space
        self.log = text_box(self, app, height=5)
        self.log.pack(side="bottom", fill="x")
        ttk.Label(self, text="INSTALLER OUTPUT", style="Muted.TLabel").pack(side="bottom", anchor="w", pady=(12, 4))
        self.table = Table(self, [("id", "Package Id", 240, "w"), ("ver", "Installed", 120, "w"),
                                  ("avail", "Available", 120, "w"), ("src", "Status", 120, "w")],
                           tree_heading="Program", on_toggle=self._counts)
        self.table.tree.column("#0", width=300)
        self.table.pack(fill="both", expand=True)
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
        self.all = ups
        self._split()
        self.app.set_status(f"{len(self.active)} updates available")

    def _split(self):
        active, skipped, ignored = updater.classify(self.all)
        self.active = active
        self.hidden = [(u, "Version skipped") for u in skipped] + [(u, "Ignored") for u in ignored]
        self._render()

    def _render(self):
        hidden_view = self.view.get() == "hidden"
        self.rb_up.config(text=f"Updates ({len(self.active)})")
        self.rb_hid.config(text=f"Skipped & ignored ({len(self.hidden)})")
        for b in (self.btn_resume, self.btn_ignore, self.btn_skip):
            b.pack_forget()
        if hidden_view:
            self.btn_resume.pack(side="right")
        else:
            self.btn_ignore.pack(side="right", padx=(8, 0))
            self.btn_skip.pack(side="right", padx=(8, 0))
        self.btn_up.state(["disabled"] if hidden_view else ["!disabled"])
        self.table.clear()
        if hidden_view:
            for u, why in self.hidden:
                self.table.add(iid=u.id, text=u.name, values=(u.id, u.version, u.available, why), tags=("muted",))
        else:
            for u in self.active:
                self.table.add(iid=u.id, text=u.name, values=(u.id, u.version, u.available, "Update ready"), check=True)
        self._counts()

    def _counts(self):
        self.cards[0].set(str(len(self.active)), "apps can be updated")
        self.cards[1].set(str(len(self.table.checked())), "will be updated")
        self.cards[2].set(str(len(self.hidden)), "hidden from updates")

    def _focused(self) -> list[updater.Upgrade]:
        ids = set(self.table.tree.selection())
        return [u for u in self.all if u.id in ids]

    def skip(self):
        sel = self._focused()
        if not sel:
            messagebox.showinfo("Woof Cleaner", "Select an app (click its name) first.", parent=self)
            return
        for u in sel:
            updater.skip_version(u.id, u.available)
        self._split()

    def ignore(self):
        sel = self._focused()
        if not sel:
            messagebox.showinfo("Woof Cleaner", "Select an app (click its name) first.", parent=self)
            return
        if confirm(self, "Ignore updates", "Never offer updates for:\n\n" + "\n".join(u.name for u in sel) +
                   "\n\nYou can resume them from 'Skipped & ignored'."):
            for u in sel:
                updater.ignore(u.id)
            self._split()

    def resume(self):
        sel = self._focused()
        if not sel:
            messagebox.showinfo("Woof Cleaner", "Select an app first.", parent=self)
            return
        for u in sel:
            updater.resume(u.id)
        self._split()

    def update_selected(self):
        ids = self.table.checked()
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
