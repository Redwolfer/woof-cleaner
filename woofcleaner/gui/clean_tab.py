"""Custom Clean: pick rules -> Analyze -> Run Cleaner."""
from __future__ import annotations

import threading
from tkinter import messagebox, ttk

from .. import settings, winutil
from ..engine import Context, Mode, human, is_applicable, run
from ..paths import BACKUP_DIR
from ..rules import load_rules
from .common import BaseTab, Table, confirm, heading, stat_row, toolbar


class CleanTab(BaseTab):
    title = "Custom Clean"
    icon = ""

    def __init__(self, parent, app, rules_file):
        super().__init__(parent, app)
        self.rs = load_rules(rules_file)
        self.by_id = self.rs.by_id()
        saved = settings.get("clean_selection")
        chosen = set(saved) if saved is not None else {r.id for r in self.rs.rules if r.default}
        self.cancel = threading.Event()
        self._save_job = None

        head = heading(self, "Custom Clean", "Remove temporary files, caches, browser traces and other junk. "
                       "Analyze shows what would go; nothing is deleted until you press Run Cleaner.")
        head.pack(fill="x")
        self.btn_cl = ttk.Button(head.actions, text="Run Cleaner", style="Accent.TButton",
                                 command=lambda: self._start(Mode.CLEAN))
        self.btn_cl.pack(side="right")
        self.btn_an = ttk.Button(head.actions, text="Analyze", command=lambda: self._start(Mode.ANALYSE))
        self.btn_an.pack(side="right", padx=8)

        bar = toolbar(self)
        ttk.Label(bar, text="Select:", style="Muted.TLabel").pack(side="left")
        ttk.Button(bar, text="Recommended", style="Ghost.TButton", command=self._recommended).pack(side="left")
        ttk.Button(bar, text="All", style="Ghost.TButton", command=lambda: self.rules.set_all(True)).pack(side="left")
        ttk.Button(bar, text="None", style="Ghost.TButton", command=lambda: self.rules.set_all(False)).pack(side="left")
        ttk.Button(bar, text="Stop", style="Danger.TButton", command=self.cancel.set).pack(side="right")
        self.sel_label = ttk.Label(bar, text="", style="Muted.TLabel")
        self.sel_label.pack(side="right", padx=12)

        self.cards = stat_row(self, [("Space to free", True), ("Files", False), ("Database records", False),
                                     ("Registry items", False)])

        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)
        self.rules = Table(paned, [], tree_heading="What to clean", selectmode="browse", on_toggle=self._toggled)
        self.rules.tree.column("#0", width=330)
        paned.add(self.rules, weight=2)
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

        right = ttk.Frame(paned)
        paned.add(right, weight=3)
        self.after(50, lambda: paned.sashpos(0, 370))
        self.table = Table(right, [("files", "Items", 80, "e"), ("size", "Size", 90, "e"), ("note", "Notes", 260, "w")],
                           tree_heading="Result")
        self.table.tree.column("#0", width=250)
        self.table.pack(fill="both", expand=True, padx=(10, 0))
        self._count()

    # ---- selection
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
        if self._save_job:
            self.after_cancel(self._save_job)
        self._save_job = self.after(600, lambda: settings.save(clean_selection=sorted(self.rules.checked())))

    def _count(self):
        self._last = set(self.rules.checked())
        self.sel_label.config(text=f"{len(self._last)} of {len(self.rs.rules)} items selected")

    # ---- run
    def _start(self, mode):
        ids = [r.id for r in self.rs.rules if r.id in self._last]
        if not ids:
            messagebox.showinfo("Woof Cleaner", "Select at least one item.", parent=self)
            return
        if mode == Mode.CLEAN and not confirm(self, "Run Cleaner", f"Permanently delete the {len(ids)} selected "
                                              "item types?\n\nTip: press Analyze first to see what will be removed."):
            return
        self.cancel.clear()
        self.table.clear()
        for b in (self.btn_an, self.btn_cl):
            b.state(["disabled"])
        ctx = Context(self.rs, mode=mode, cancel=self.cancel, backup_dir=BACKUP_DIR, progress=self.status)
        self.run_bg(lambda: run(ids, ctx), lambda res: self._show(mode, res),
                    "Analyzing ..." if mode == Mode.ANALYSE else "Cleaning ...")

    def _finish_err(self, err):
        for b in (self.btn_an, self.btn_cl):
            b.state(["!disabled"])
        super()._finish_err(err)

    def _show(self, mode, results):
        for b in (self.btn_an, self.btn_cl):
            b.state(["!disabled"])
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
            for path, size in r.items[:300]:
                self.table.add(text=path, values=("", human(size) if size else "", ""), parent=node, tags=("muted",))
            for e in r.errors[:5]:
                self.table.add(text="⚠ " + e, values=("", "", ""), parent=node, tags=("warn",))
        clean = mode == Mode.CLEAN
        self.cards[0].set(human(tb), "freed" if clean else "can be freed")
        self.cards[1].set(f"{tf:,}", "deleted" if clean else "found")
        self.cards[2].set(f"{trec:,}", "history, cookies, logs")
        self.cards[3].set(f"{treg:,}", "")
        verb = "Cleaning complete: freed" if clean else "Analysis complete: you can free"
        self.app.set_status("Stopped" if self.cancel.is_set() else f"{verb} {human(tb)}")
