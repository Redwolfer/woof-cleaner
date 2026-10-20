"""Scheduled cleaning page: create / toggle / run / delete schedules, see the run history."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .. import scheduler, settings, winutil
from ..engine import human
from .common import BaseTab, Table, confirm, heading

TIMES = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)]


class ScheduleTab(BaseTab):
    title = "Scheduled Cleaning"
    icon = ""

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.items: list[scheduler.Schedule] = []
        heading(self, "Scheduled Cleaning", "Keep your PC clean automatically. A schedule runs Custom Clean with "
                "the items you ticked there; if the PC is off at that time, it runs the next time it is on."
                ).pack(fill="x", pady=(0, 14))

        form = ttk.Frame(self, style="Card.TFrame", padding=(18, 14))
        form.pack(fill="x", pady=(0, 14))
        ttk.Label(form, text="New schedule", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=8, sticky="w")
        ttk.Label(form, text="Frequency", style="CardMuted.TLabel").grid(row=1, column=0, sticky="w", pady=(10, 2))
        ttk.Label(form, text="Day", style="CardMuted.TLabel").grid(row=1, column=1, sticky="w", padx=(12, 0), pady=(10, 2))
        ttk.Label(form, text="Time", style="CardMuted.TLabel").grid(row=1, column=2, sticky="w", padx=(12, 0), pady=(10, 2))
        self.freq = tk.StringVar(value=scheduler.FREQUENCIES["biweekly"] + " (recommended)")
        self._freq_map = {scheduler.FREQUENCIES["biweekly"] + " (recommended)": "biweekly",
                          scheduler.FREQUENCIES["weekly"]: "weekly", scheduler.FREQUENCIES["daily"]: "daily",
                          scheduler.FREQUENCIES["logon"]: "logon"}
        cb = ttk.Combobox(form, textvariable=self.freq, values=list(self._freq_map), state="readonly", width=28)
        cb.grid(row=2, column=0, sticky="w")
        cb.bind("<<ComboboxSelected>>", lambda _e: self._freq_changed())
        self.day = tk.StringVar(value="Monday")
        self.day_cb = ttk.Combobox(form, textvariable=self.day, values=scheduler.DAYS, state="readonly", width=14)
        self.day_cb.grid(row=2, column=1, sticky="w", padx=(12, 0))
        self.time = tk.StringVar(value="10:00")
        self.time_cb = ttk.Combobox(form, textvariable=self.time, values=TIMES, width=8)
        self.time_cb.grid(row=2, column=2, sticky="w", padx=(12, 0))
        self.elev = tk.BooleanVar(value=False)
        self.elev_cb = ttk.Checkbutton(form, text="Run with administrator rights (also cleans Windows folders)",
                                       variable=self.elev, style="Card.TCheckbutton")
        self.elev_cb.grid(row=3, column=0, columnspan=6, sticky="w", pady=(10, 0))
        if not winutil.is_admin():
            self.elev_cb.state(["disabled"])
        ttk.Button(form, text="Add schedule", style="Accent.TButton", command=self.add).grid(row=2, column=7, sticky="e")
        form.columnconfigure(6, weight=1)
        self.sel_info = ttk.Label(form, text="", style="CardMuted.TLabel")
        self.sel_info.grid(row=4, column=0, columnspan=8, sticky="w", pady=(8, 0))

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 10))
        ttk.Label(bar, text="Your schedules", style="H2.TLabel").pack(side="left")
        ttk.Button(bar, text="Delete", style="Danger.TButton", command=self.delete).pack(side="right")
        ttk.Button(bar, text="Run now", command=self.run_now).pack(side="right", padx=8)
        ttk.Button(bar, text="Turn off", command=lambda: self.toggle(False)).pack(side="right")
        ttk.Button(bar, text="Turn on", command=lambda: self.toggle(True)).pack(side="right", padx=8)

        self.table = Table(self, [("state", "Status", 90, "w"), ("next", "Next run", 150, "w"),
                                  ("last", "Last run", 150, "w"), ("result", "Result", 160, "w"),
                                  ("rights", "Rights", 110, "w")], tree_heading="Schedule", height=4)
        self.table.tree.column("#0", width=280)
        self.table.pack(fill="x")

        hb = ttk.Frame(self)
        hb.pack(fill="x", pady=(16, 8))
        ttk.Label(hb, text="Recent automatic cleans", style="H2.TLabel").pack(side="left")
        self.hist_info = ttk.Label(hb, text="", style="Muted.TLabel")
        self.hist_info.pack(side="right")
        self.hist = Table(self, [("trigger", "Started by", 140, "w"), ("freed", "Freed", 100, "e"),
                                 ("files", "Files", 90, "e"), ("records", "Records", 90, "e"),
                                 ("errors", "Errors", 80, "e")], tree_heading="When", height=6)
        self.hist.pack(fill="both", expand=True)

    def on_show(self):
        self.refresh()

    def _freq_changed(self):
        f = self._freq_map[self.freq.get()]
        self.day_cb.state(["!disabled"] if f in ("weekly", "biweekly") else ["disabled"])
        self.time_cb.state(["disabled"] if f == "logon" else ["!disabled"])

    def refresh(self):
        self.run_bg(scheduler.list_schedules, self._loaded, "Reading schedules ...")

    def _loaded(self, items):
        self.items = items
        self.table.clear()
        for s in items:
            ok = s.last_result in ("", "OK", "running")
            self.table.add(iid=s.id, text=s.description, tags=() if s.enabled and ok else ("off",) if not s.enabled else ("warn",),
                           values=("● On" if s.enabled else "○ Off", s.next_run or "–", s.last_run or "never",
                                   s.last_result or "–", "Administrator" if s.elevated else "Standard"))
        hist = list(reversed(settings.get("autoclean_history", [])))
        self.hist.clear()
        names = {s.id: s.description for s in items}
        for h in hist[:50]:
            trig = h.get("trigger", "")
            self.hist.add(text=h.get("time", ""), values=(names.get(trig, "Sign-in" if trig == "logon" else trig.title()),
                                                          human(h.get("freed", 0)), f"{h.get('files', 0):,}",
                                                          f"{h.get('records', 0):,}", h.get("errors", 0)))
        self.hist_info.config(text=f"{human(sum(h.get('freed', 0) for h in hist))} freed in {len(hist)} automatic "
                                   f"clean(s)  ·  {sum(s.enabled for s in items)} of {len(items)} schedule(s) on")
        sel = settings.get("clean_selection")
        self.sel_info.config(text=(f"Scheduled cleans use your Custom Clean selection ({len(sel)} items)." if sel else
                                   "Scheduled cleans use the recommended Custom Clean items.") +
                             ("  Items that need administrator rights are skipped unless the schedule has them."))
        self._freq_changed()

    def add(self):
        f = self._freq_map[self.freq.get()]
        try:
            scheduler.add_schedule(f, self.day.get(), self.time.get().strip(), self.elev.get())
        except (OSError, ValueError) as e:
            messagebox.showerror("Woof Cleaner", f"Could not create the schedule:\n{e}", parent=self)
            return
        self.refresh()

    def _sel(self) -> list[scheduler.Schedule]:
        ids = set(self.table.tree.selection())
        out = [s for s in self.items if s.id in ids]
        if not out:
            messagebox.showinfo("Woof Cleaner", "Select a schedule first.", parent=self)
        return out

    def toggle(self, on: bool):
        for s in self._sel():
            try:
                scheduler.set_enabled(s.id, on)
            except OSError as e:
                messagebox.showerror("Woof Cleaner", str(e), parent=self)
        self.refresh()

    def run_now(self):
        sel = self._sel()
        if sel and confirm(self, "Run now", "Run this scheduled clean now? It cleans without asking again."):
            for s in sel:
                try:
                    scheduler.run_now(s.id)
                except OSError as e:
                    messagebox.showerror("Woof Cleaner", str(e), parent=self)
            self.app.set_status("Scheduled clean started in the background. Refresh in a moment to see the result.")
            self.after(8000, self.refresh)

    def delete(self):
        sel = self._sel()
        if sel and confirm(self, "Delete schedule", "Delete " + ", ".join(s.description for s in sel) + "?"):
            for s in sel:
                try:
                    scheduler.remove_schedule(s.id)
                except OSError as e:
                    messagebox.showerror("Woof Cleaner", str(e), parent=self)
            self.refresh()
