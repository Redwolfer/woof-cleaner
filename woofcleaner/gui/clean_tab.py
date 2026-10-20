"""Custom Clean: pick rules -> Analyze -> Run Cleaner."""
from __future__ import annotations

import threading
from tkinter import messagebox, ttk

from .. import winutil
from ..engine import Context, Mode, human, is_applicable, run
from ..rules import load_rules
from .common import OFF, ON, BaseTab, Table, confirm, heading


class CleanTab(BaseTab):
    title = "\U0001F9F9 Custom Clean"

    def __init__(self, nb, app, rules_file):
        super().__init__(nb, app)
        from ..cli import BACKUP_DIR as bd
        self.backup_dir = bd
        self.rs = load_rules(rules_file)
        self.checked = {r.id: r.default for r in self.rs.rules}
        self.cancel = threading.Event()

        heading(self, "Custom Clean", "Remove temporary files, caches and traces. Analyze first: nothing is "
                "deleted until you press Run Cleaner.").pack(fill="x", pady=(0, 8))
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left = ttk.Frame(paned)
        paned.add(left, weight=1)
        self.tree = ttk.Treeview(left, show="tree", selectmode="browse")
        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.bind("<Button-1>", self._click)
        ctx = Context(self.rs)
        admin = winutil.is_admin()
        self.group_nodes: dict[str, str] = {}
        self.node_rule: dict[str, str] = {}
        for r in self.rs.rules:
            if r.group not in self.group_nodes:
                self.group_nodes[r.group] = self.tree.insert("", "end", text=f"{OFF}  {r.group}", open=True)
            label = r.name + ("" if is_applicable(r, ctx) else "  (not found)")
            if r.needs_admin and not admin:
                label += "  (needs admin)"
            node = self.tree.insert(self.group_nodes[r.group], "end", text=f"{OFF}  {label}")
            self.node_rule[node] = r.id
        self._refresh_marks()

        right = ttk.Frame(paned)
        paned.add(right, weight=2)
        bar = ttk.Frame(right)
        bar.pack(fill="x")
        self.btn_an = ttk.Button(bar, text="Analyze", command=lambda: self._start(Mode.ANALYSE))
        self.btn_an.pack(side="left")
        self.btn_cl = ttk.Button(bar, text="Run Cleaner", style="Accent.TButton", command=lambda: self._start(Mode.CLEAN))
        self.btn_cl.pack(side="left", padx=6)
        ttk.Button(bar, text="Stop", command=self.cancel.set).pack(side="left")
        self.table = Table(right, [("files", "Files", 70, "e"), ("size", "Size", 90, "e"), ("note", "Notes", 320, "w")],
                           tree_heading="Item")
        self.table.pack(fill="both", expand=True, pady=6)
        self.total = ttk.Label(right, text="Pick items, then press Analyze.", style="Big.TLabel")
        self.total.pack(anchor="w")

    def _group_all(self, g):
        return all(self.checked[r.id] for r in self.rs.rules if r.group == g)

    def _click(self, ev):
        node = self.tree.identify_row(ev.y)
        if not node or self.tree.identify_region(ev.x, ev.y) not in ("tree", "cell"):
            return
        if node in self.node_rule:
            rid = self.node_rule[node]
            self.checked[rid] = not self.checked[rid]
        else:
            g = next(k for k, v in self.group_nodes.items() if v == node)
            new = not self._group_all(g)
            for r in self.rs.rules:
                if r.group == g:
                    self.checked[r.id] = new
        self._refresh_marks()
        return "break"

    def _refresh_marks(self):
        for node, rid in self.node_rule.items():
            t = self.tree.item(node, "text")
            self.tree.item(node, text=(ON if self.checked[rid] else OFF) + t[1:])
        for g, node in self.group_nodes.items():
            t = self.tree.item(node, "text")
            self.tree.item(node, text=(ON if self._group_all(g) else OFF) + t[1:])

    def _start(self, mode):
        ids = [r.id for r in self.rs.rules if self.checked[r.id]]
        if not ids:
            messagebox.showinfo("Woof Cleaner", "Select at least one item.", parent=self)
            return
        if mode == Mode.CLEAN and not confirm(self, "Run Cleaner", "Permanently delete the selected items?\n\n"
                                              "Tip: press Analyze first to see what will be removed."):
            return
        self.cancel.clear()
        self.table.clear()
        ctx = Context(self.rs, mode=mode, cancel=self.cancel, backup_dir=self.backup_dir, progress=self.status)
        self.run_bg(lambda: run(ids, ctx), lambda res: self._show(mode, res),
                    "Analyzing ..." if mode == Mode.ANALYSE else "Cleaning ...")

    def _show(self, mode, results):
        tf = tb = 0
        tree = self.table.tree
        for r in results:
            if not r.applicable:
                continue
            tf, tb = tf + r.files, tb + r.bytes
            note = "; ".join(r.notes)
            if r.skipped_locked:
                note = f"{r.skipped_locked} in use/skipped. " + note
            node = tree.insert("", "end", text=r.name, values=(r.files, human(r.bytes), note))
            for path, size in r.items[:200]:
                tree.insert(node, "end", text=path, values=("", human(size), ""))
            for e in r.errors[:5]:
                tree.insert(node, "end", text="! " + e, values=("", "", ""))
        verb = "Analysis complete - can free" if mode == Mode.ANALYSE else "Cleaning complete - freed"
        self.total.config(text=f"{verb} {human(tb)} ({tf} files)")
        self.app.set_status("Stopped" if self.cancel.is_set() else "Done")
