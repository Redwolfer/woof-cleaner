"""Custom Clean: pick rules -> Analyze -> Run Cleaner."""
from __future__ import annotations

from collections import Counter
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from .. import scheduler, settings, winutil
from ..engine import Context, Mode, human, is_applicable, run
from ..paths import BACKUP_DIR
from ..rules import load_rules
from .folders import edit_folders
from .common import BaseTab, Table, heading, toolbar


class CleanTab(BaseTab):
    title = "Custom Clean"
    icon = ""

    def __init__(self, parent, app, rules_file):
        super().__init__(parent, app)
        self.rs = load_rules(rules_file)
        self.by_id = self.rs.by_id()
        saved = settings.get("clean_selection")
        chosen = set(self.rs.selection(saved))
        self.cancel = threading.Event()
        self.last_results = None

        head = heading(self, "Custom Clean", "Choose what to clean. Analyze previews the selected items.")
        head.pack(fill="x")
        self.btn_cl = ttk.Button(head.actions, text="Run Cleaner",
                                 command=lambda: self._start(Mode.CLEAN))
        self.btn_cl.pack(side="right")
        self.btn_an = ttk.Button(head.actions, text="Analyze", style="Accent.TButton", command=lambda: self._start(Mode.ANALYSE))
        self.btn_an.pack(side="right", padx=8)

        bar = toolbar(self)
        select = ttk.Menubutton(bar, text="Selection")
        menu = tk.Menu(select, tearoff=False)
        menu.add_command(label="Recommended", command=self._recommended)
        menu.add_command(label="All", command=lambda: self.rules.set_all(True))
        menu.add_command(label="None", command=lambda: self.rules.set_all(False))
        select.configure(menu=menu)
        select.pack(side="left")
        self.folders = ttk.Button(bar, text="Folders…", command=self._folders)
        self.folders.pack(side="left", padx=4)
        self.export = ttk.Button(bar, text="Export CSV", command=self._export)
        self.export.pack(side="left")
        self.export.state(["disabled"])
        self.stop = ttk.Button(bar, text="Stop", command=self._stop)
        self.stop.state(["disabled"])
        self.sel_label = ttk.Label(bar, text="", style="Muted.TLabel")
        self.sel_label.pack(side="right", padx=12)

        self.summary = ttk.Label(self, text="", style="H2.TLabel", wraplength=760)

        self.panes = paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)
        self.rules = Table(paned, [], tree_heading="What to clean", selectmode="browse", on_toggle=self._toggled)
        self.rules.tree.column("#0", width=330)
        paned.add(self.rules, weight=2)
        self._populate(chosen)

        right = ttk.Frame(paned)
        paned.add(right, weight=3)
        self.after(50, lambda: paned.sashpos(0, min(370, int(paned.winfo_width() * 0.43))))
        self.table = Table(right, [("files", "Items", 80, "e"), ("size", "Size", 90, "e"), ("note", "Notes", 260, "w")],
                           tree_heading="Result")
        self.table.tree.column("#0", width=250)
        self.table.pack(fill="both", expand=True, padx=(10, 0))
        self._count()

    # ---- selection
    def _export(self):
        from .export import save_csv
        from ..reports import clean_rows
        save_csv(self, "custom-clean", clean_rows(self.last_results))

    def _folders(self):
        if self.busy or not edit_folders(self):
            return
        self.rs = load_rules(self.app.rules_file)
        self.by_id = self.rs.by_id()
        self.rules.clear()
        self._populate(self.rs.selection(settings.get("clean_selection")))
        self._toggled(warn=False)

    def _populate(self, chosen):
        ctx = Context(self.rs)
        admin = winutil.is_admin()
        groups: dict[str, str] = {}
        for r in self.rs.rules:
            if r.group not in groups:
                groups[r.group] = self.rules.group(text=r.group, open=r.group in ("System", "Browsers"))
            label = r.name
            tags = ()
            if not is_applicable(r, ctx):
                label += "  ·  not installed"
                tags = ("muted",)
            elif r.needs_admin and not admin:
                label += "  ·  needs admin"
                tags = ("muted",)
            self.rules.add(iid=r.id, text=label, parent=groups[r.group], check=r.id in chosen, tags=tags)

    def _recommended(self):
        for r in self.rs.rules:
            self.rules.set_checked(r.id, r.default)
        self._toggled(warn=False)

    def _toggled(self, warn: bool = True):
        sel = set(self.rules.checked())
        if warn:
            newly = [i for i in sel - self._last if self.by_id[i].warning]
            if len(newly) == 1:
                r = self.by_id[newly[0]]
                if not messagebox.askokcancel(f"About \"{r.name}\"", r.warning, icon="warning", parent=self):
                    self.rules.set_checked(r.id, False)
                    sel.discard(r.id)
        self._count()
        settings.save(clean_selection=sorted(self._last))

    def _count(self):
        self._last = set(self.rules.checked())
        self.sel_label.config(text=f"{len(self._last)} selected")
        if self.last_results is None and not self.busy:
            self.table.clear()
            self.table.tree.heading("#0", text="Selected categories")
            self.table.tree.heading("files", text="Rules")
            self.table.tree.configure(displaycolumns=("files",))
            for group, count in Counter(r.group for r in self.rs.rules if r.id in self._last).items():
                self.table.add(text=group, values=(count, "", ""))
            if not self._last:
                self.table.add(text="Choose a rule to analyze")

    # ---- run
    def _stop(self):
        self.cancel.set()
        self.stop.state(["disabled"])
        self.app.set_status("Cancelling…")

    def _start(self, mode):
        if self.busy:
            return
        ids = [r.id for r in self.rs.rules if r.id in self._last]
        if not ids:
            messagebox.showinfo("Woof Cleaner", "Select at least one item.", parent=self)
            return
        if mode == Mode.CLEAN and not messagebox.askokcancel(
            "Run Cleaner", f"Permanently clean data matching {len(ids)} selected rules?",
            icon="warning", default="cancel", parent=self
        ):
            self.btn_cl.focus_set()
            return
        self.cancel.clear()
        self.stop.pack(side="right")
        self.stop.state(["!disabled"])
        self.table.clear()
        self.table.tree.configure(displaycolumns="#all")
        self.table.tree.heading("#0", text="Result")
        self.table.tree.heading("files", text="Items")
        self.summary.pack_forget()
        self.export.state(["disabled"])
        for b in (self.btn_an, self.btn_cl):
            b.state(["disabled"])
        ctx = Context(self.rs, mode=mode, cancel=self.cancel, backup_dir=BACKUP_DIR, progress=self.status)
        def work():
            results = run(ids, ctx)
            try:
                scheduler.record_results(results, mode, "Custom Clean", self.cancel.is_set())
            except OSError as error:
                self.app.post(lambda text=str(error): messagebox.showwarning(
                    "History could not be saved", text, parent=self))
            return results
        self.run_bg(work, lambda res: self._show(mode, res),
                    "Analyzing ..." if mode == Mode.ANALYSE else "Cleaning ...")

    def status(self, msg):
        self.app.post(lambda: self.app.set_status(msg) if not self.cancel.is_set() else None)

    def _finish_err(self, err):
        self.stop.pack_forget()
        for b in (self.btn_an, self.btn_cl):
            b.state(["!disabled"])
        super()._finish_err(err)

    def _show(self, mode, results):
        self.stop.pack_forget()
        self.last_results = results
        self.export.state(["!disabled"])
        self._rows = self._result_rows(mode, results)
        self._render_results()

    def _render_results(self):
        deadline = time.monotonic() + 0.006
        while time.monotonic() < deadline:
            if next(self._rows, None) is None:
                for button in (self.btn_an, self.btn_cl):
                    button.state(["!disabled"])
                return
        self.after(1, self._render_results)

    def _result_rows(self, mode, results):
        tf = tb = trec = treg = 0
        for r in results:
            if not r.applicable:
                continue
            tf, tb, trec, treg = tf + r.files, tb + r.bytes, trec + r.records, treg + r.reg_items
            note = "; ".join(r.notes)
            if r.skipped_locked:
                note = f"{r.skipped_locked} in use, skipped. " + note
            count = r.files + r.records + r.reg_items
            tags = ("muted",) if not r.found_anything else ()
            node = self.table.add(text=r.name, values=(f"{count:,}", human(r.bytes) if r.bytes else "", note),
                                  open=False, tags=tags)
            yield True
            for path, size in r.items:
                self.table.add(text=path, values=("", human(size) if size else "", ""), parent=node, tags=("muted",))
                yield True
            for e in r.errors[:5]:
                self.table.add(text="⚠ " + e, values=("", "", ""), parent=node, tags=("warn",))
        clean = mode == Mode.CLEAN
        title = f"{human(tb)} freed" if clean else f"{human(tb)} to free"
        self.summary.config(text=f"{title}   ·   {tf:,} files   ·   {trec:,} records   ·   {treg:,} registry items")
        self.summary.pack(before=self.panes, fill="x", pady=(0, 8))
        verb = "Cleaning complete: freed" if clean else "Analysis complete: you can free"
        if self.cancel.is_set():
            status = "Stopped. Showing partial results."
        elif any(r.errors or r.skipped_locked for r in results):
            status = f"{verb} {human(tb)}. Some items were skipped. Review the details."
        elif not any(r.found_anything for r in results):
            status = "No matching items found. Review your selection to scan other locations."
        else:
            status = f"{verb} {human(tb)}"
        self.app.set_status(status)
