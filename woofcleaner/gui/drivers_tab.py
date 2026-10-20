"""Driver Updater tab (Windows Update driver catalogue)."""
from __future__ import annotations

from tkinter import messagebox, ttk

from .. import drivers as drv
from .common import OFF, ON, BaseTab, Table, confirm, heading


class DriversTab(BaseTab):
    title = "\U0001F527 Driver Updater"

    def __init__(self, nb, app):
        super().__init__(nb, app)
        self.updates: list[drv.DriverUpdate] = []
        self.checked: set[str] = set()
        heading(self, "Driver Updater", "Checks Windows Update for newer Microsoft-certified drivers and installs "
                "them (needs administrator; one UAC prompt). Also lists devices that have driver problems.").pack(fill="x", pady=(0, 8))
        bar = ttk.Frame(self)
        bar.pack(fill="x")
        ttk.Button(bar, text="Scan for driver updates", command=self.scan).pack(side="left")
        ttk.Button(bar, text="Device Manager", command=drv.open_device_manager).pack(side="left", padx=6)
        ttk.Button(bar, text="Install selected", style="Accent.TButton", command=self.install).pack(side="right")

        ttk.Label(self, text="Available driver updates", style="Big.TLabel").pack(anchor="w", pady=(8, 0))
        self.up_table = Table(self, [("cls", "Class", 110, "w"), ("maker", "Manufacturer", 140, "w"),
                                     ("date", "Driver date", 90, "w"), ("size", "Download", 80, "e")],
                              tree_heading="Update", height=6)
        self.up_table.pack(fill="both", expand=True, pady=4)
        self.up_table.tree.bind("<Button-1>", self._toggle)

        ttk.Label(self, text="Devices with problems", style="Big.TLabel").pack(anchor="w", pady=(6, 0))
        self.prob_table = Table(self, [("dev", "Device", 340, "w"), ("problem", "Problem", 200, "w"),
                                       ("id", "Hardware id", 360, "w")], height=3)
        self.prob_table.pack(fill="x", pady=4)

        ttk.Label(self, text="Installed drivers", style="Big.TLabel").pack(anchor="w", pady=(6, 0))
        self.inst_table = Table(self, [("dev", "Device", 300, "w"), ("cls", "Class", 110, "w"),
                                       ("ver", "Version", 130, "w"), ("date", "Date", 90, "w"),
                                       ("prov", "Provider", 160, "w")], height=6)
        self.inst_table.pack(fill="both", expand=True, pady=4)

    def on_show(self):
        self.run_bg(lambda: (drv.installed_drivers(), drv.problem_devices()), self._inventory, "Reading drivers ...")

    def _inventory(self, data):
        installed, problems = data
        self.inst_table.clear()
        for d in installed:
            self.inst_table.tree.insert("", "end", values=(d.device, d.cls, d.version, d.date, d.provider))
        self.prob_table.clear()
        for p in problems:
            self.prob_table.tree.insert("", "end", values=(p.device, p.problem, p.pnp_id))
        self.app.set_status(f"{len(installed)} drivers, {len(problems)} device problem(s). "
                            "Press 'Scan for driver updates' to check Windows Update.")

    def scan(self):
        self.run_bg(drv.search_updates, self._loaded, "Searching Windows Update for drivers (may take a minute) ...")

    def _loaded(self, updates):
        self.updates = updates
        self.checked = {u.update_id for u in updates}
        self._render()
        self.app.set_status(f"{len(updates)} driver update(s) available")

    def _render(self):
        self.up_table.clear()
        for u in self.updates:
            mark = ON if u.update_id in self.checked else OFF
            self.up_table.tree.insert("", "end", iid=u.update_id, text=f"{mark}  {u.title}",
                                      values=(u.cls, u.manufacturer, u.date, f"{u.size_mb:.1f} MB"))

    def _toggle(self, ev):
        iid = self.up_table.tree.identify_row(ev.y)
        if not iid or self.up_table.tree.identify_region(ev.x, ev.y) != "tree":
            return
        self.checked ^= {iid}
        self._render()
        return "break"

    def install(self):
        ids = [u.update_id for u in self.updates if u.update_id in self.checked]
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
