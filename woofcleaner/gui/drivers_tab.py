"""Driver Updater page (Windows Update driver catalogue) with Skip / Ignore."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .. import drivers as drv
from .common import BaseTab, Table, confirm, heading, stat_row, toolbar


class DriversTab(BaseTab):
    title = "Driver Updater"
    icon = ""

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.found: list[drv.DriverUpdate] = []
        self.status_of: dict[str, str] = {}
        head = heading(self, "Driver Updater", "Checks Windows Update for newer Microsoft-certified drivers and "
                       "installs them (one administrator prompt, with a restore point first). Also lists devices "
                       "that have driver problems.")
        head.pack(fill="x")
        ttk.Button(head.actions, text="Install selected", style="Accent.TButton", command=self.install).pack(side="right")
        ttk.Button(head.actions, text="Scan for driver updates", command=self.scan).pack(side="right", padx=8)

        self.cards = stat_row(self, [("Driver updates", True), ("Device problems", False), ("Installed drivers", False)])
        self.cards[0].set("–", "press Scan")

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)

        up = ttk.Frame(self.nb, padding=(0, 12, 0, 0))
        self.nb.add(up, text="Driver updates")
        bar = toolbar(up, pady=(0, 10))
        self.show_hidden = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Show skipped & ignored", variable=self.show_hidden, command=self._render).pack(side="left")
        ttk.Button(bar, text="Device Manager", style="Ghost.TButton", command=drv.open_device_manager).pack(side="left", padx=12)
        ttk.Button(bar, text="Resume", command=self.resume).pack(side="right")
        ttk.Button(bar, text="Ignore device", command=self.ignore).pack(side="right", padx=8)
        ttk.Button(bar, text="Skip update", command=self.skip).pack(side="right")
        self.up_table = Table(up, [("cls", "Class", 110, "w"), ("maker", "Manufacturer", 150, "w"),
                                   ("date", "Driver date", 100, "w"), ("size", "Download", 90, "e"),
                                   ("state", "Status", 110, "w")], tree_heading="Update")
        self.up_table.tree.column("#0", width=380)
        self.up_table.pack(fill="both", expand=True)

        pr = ttk.Frame(self.nb, padding=(0, 12, 0, 0))
        self.nb.add(pr, text="Devices with problems")
        self.prob_table = Table(pr, [("problem", "Problem", 260, "w"), ("id", "Hardware id", 420, "w")],
                                tree_heading="Device")
        self.prob_table.pack(fill="both", expand=True)

        inst = ttk.Frame(self.nb, padding=(0, 12, 0, 0))
        self.nb.add(inst, text="Installed drivers")
        self.inst_table = Table(inst, [("cls", "Class", 120, "w"), ("ver", "Version", 140, "w"),
                                       ("date", "Date", 100, "w"), ("prov", "Provider", 180, "w")],
                                tree_heading="Device")
        self.inst_table.tree.column("#0", width=340)
        self.inst_table.pack(fill="both", expand=True)

    def on_show(self):
        self.run_bg(lambda: (drv.installed_drivers(), drv.problem_devices()), self._inventory, "Reading drivers ...")

    def _inventory(self, data):
        installed, problems = data
        self.inst_table.clear()
        for d in installed:
            self.inst_table.add(text=d.device, values=(d.cls, d.version, d.date, d.provider))
        self.prob_table.clear()
        for p in problems:
            self.prob_table.add(text=p.device, values=(p.problem, p.pnp_id), tags=("warn",))
        self.nb.tab(1, text=f"Devices with problems ({len(problems)})")
        self.nb.tab(2, text=f"Installed drivers ({len(installed)})")
        self.cards[1].set(str(len(problems)), "need attention" if problems else "all devices OK")
        self.cards[2].set(str(len(installed)), "")
        self.app.set_status(f"{len(installed)} drivers, {len(problems)} device problem(s). "
                            "Press 'Scan for driver updates' to check Windows Update.")

    def scan(self):
        self.run_bg(drv.search_updates, self._loaded, "Searching Windows Update for drivers (may take a minute) ...")

    def _loaded(self, updates):
        self.found = updates
        self._render()
        self.app.set_status(f"{self.cards[0].value.cget('text')} driver update(s) available")

    def _render(self):
        active, skipped, ignored = drv.classify(self.found)
        self.status_of = {u.update_id: "Ready" for u in active}
        self.status_of.update({u.update_id: "Skipped" for u in skipped})
        self.status_of.update({u.update_id: "Device ignored" for u in ignored})
        self.up_table.clear()
        for u in self.found:
            state = self.status_of[u.update_id]
            if state != "Ready" and not self.show_hidden.get():
                continue
            self.up_table.add(iid=u.update_id, text=u.title, check=True if state == "Ready" else None,
                              values=(u.cls, u.manufacturer, u.date, f"{u.size_mb:.1f} MB", state),
                              tags=() if state == "Ready" else ("muted",))
        self.cards[0].set(str(len(active)), f"{len(skipped) + len(ignored)} skipped or ignored" if skipped or ignored
                          else "ready to install")
        self.nb.tab(0, text=f"Driver updates ({len(active)})")

    def _selected(self) -> list[drv.DriverUpdate]:
        ids = set(self.up_table.tree.selection())
        return [u for u in self.found if u.update_id in ids]

    def skip(self):
        for u in self._selected():
            drv.skip_update(u)
        self._render()

    def ignore(self):
        sel = self._selected()
        if sel and confirm(self, "Ignore device", "Never offer driver updates for these devices?\n\n" +
                           "\n".join(u.title for u in sel)):
            for u in sel:
                drv.ignore_device(u)
            self._render()

    def resume(self):
        for u in self._selected():
            drv.resume(u)
        self._render()

    def install(self):
        ids = [i for i in self.up_table.checked() if self.status_of.get(i) == "Ready"]
        if not ids:
            messagebox.showinfo("Woof Cleaner", "Scan first, then tick the drivers to install.", parent=self)
            return
        if not confirm(self, "Install drivers", f"Install {len(ids)} driver update(s) from Windows Update?\n\n"
                       "Windows will ask for administrator permission. A system restore point is created first "
                       "(when System Protection is enabled)."):
            return
        self.run_bg(lambda: drv.install_updates(ids), self._installed, "Downloading and installing drivers ...")

    def _installed(self, report):
        lines, reboot = [], False
        for r in report:
            if r.get("Title") == "__error__":
                lines.append("Error: " + str(r.get("Message")))
            elif r.get("Title") == "__summary__":
                reboot = bool(r.get("Reboot"))
            elif r.get("Title") == "__restorepoint__":
                lines.insert(0, f"System restore point: {r.get('Message')}\n")
            else:
                lines.append(f"{r['Title']}: {drv.RESULT_CODES.get(r['Result'], r['Result'])}")
        if reboot:
            lines.append("\nRestart Windows to finish installing.")
        messagebox.showinfo("Woof Cleaner", "\n".join(lines) or "Nothing was installed.", parent=self)
        self.scan()
