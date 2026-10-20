"""Shared GUI plumbing: background jobs, sortable tables, size formatting."""
from __future__ import annotations

import re
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

ACCENT = "#c96f2d"   # warm "woof" orange
ON, OFF = "☑", "☐"

_UNITS = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}


def sort_value(text: str):
    """Sort key that understands sizes ('1.2 MB'), versions/numbers and dates."""
    t = (text or "").strip()
    m = re.fullmatch(r"([\d.]+)\s*(B|KB|MB|GB|TB)", t)
    if m:
        return (0, float(m.group(1)) * _UNITS[m.group(2)], "")
    if re.fullmatch(r"\d+(\.\d+)*", t):
        return (0, 0, tuple(int(p) for p in t.split(".")))
    return (1, 0, t.lower())


class Table(ttk.Frame):
    """Treeview + scrollbars + click-to-sort headings."""

    def __init__(self, parent, columns: list[tuple[str, str, int, str]], tree_heading: str | None = None,
                 selectmode="extended", height=14):
        super().__init__(parent)
        ids = [c[0] for c in columns]
        show = "tree headings" if tree_heading else "headings"
        self.tree = ttk.Treeview(self, columns=ids, show=show, selectmode=selectmode, height=height)
        if tree_heading:
            self.tree.heading("#0", text=tree_heading, command=lambda: self.sort("#0"))
            self.tree.column("#0", width=280, stretch=True)
        for cid, title, width, anchor in columns:
            self.tree.heading(cid, text=title, command=lambda c=cid: self.sort(c))
            self.tree.column(cid, width=width, anchor=anchor, stretch=anchor == "w")
        ys = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        xs = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self._desc: dict[str, bool] = {}

    def clear(self):
        self.tree.delete(*self.tree.get_children())

    def sort(self, col: str):
        desc = self._desc[col] = not self._desc.get(col, False)
        get = (lambda i: self.tree.item(i, "text")) if col == "#0" else (lambda i: self.tree.set(i, col))
        items = sorted(self.tree.get_children(""), key=lambda i: sort_value(get(i)), reverse=desc)
        for n, i in enumerate(items):
            self.tree.move(i, "", n)


class BaseTab(ttk.Frame):
    title = "Tab"

    def __init__(self, notebook, app):
        super().__init__(notebook, padding=10)
        self.app = app
        self.busy = False

    def status(self, msg: str):
        self.app.post(lambda: self.app.set_status(msg))

    def run_bg(self, work: Callable[[], Any], done: Callable[[Any], None], label: str = "Working ..."):
        """Run work() on a thread; done(result) on the UI thread. Errors become a message box."""
        if self.busy:
            return
        self.busy = True
        self.app.set_busy(True, label)

        def runner():
            try:
                result = work()
            except Exception as e:  # report every failure to the user
                err = e
                self.app.post(lambda: self._finish_err(err))
                return
            self.app.post(lambda: self._finish_ok(done, result))

        threading.Thread(target=runner, daemon=True).start()

    def _finish_ok(self, done, result):
        self.busy = False
        self.app.set_busy(False)
        done(result)

    def _finish_err(self, err):
        self.busy = False
        self.app.set_busy(False)
        self.app.set_status("Error")
        messagebox.showerror("Woof Cleaner", str(err), parent=self)

    def on_show(self):
        """Called the first time the tab becomes visible (lazy loading)."""


def heading(parent, text: str, sub: str = ""):
    f = ttk.Frame(parent)
    ttk.Label(f, text=text, style="H1.TLabel").pack(anchor="w")
    if sub:
        ttk.Label(f, text=sub, style="Sub.TLabel", wraplength=900, justify="left").pack(anchor="w", pady=(2, 0))
    return f


def confirm(parent, title: str, text: str) -> bool:
    return messagebox.askyesno(title, text, icon="warning", parent=parent)
