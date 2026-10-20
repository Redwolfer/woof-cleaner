"""Woof Cleaner main window: a sidebar of tools, each tool is a tab."""
from __future__ import annotations

import queue
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from .. import __version__, paths, selfupdate, winutil
from .common import ACCENT
from .update_dialog import check_for_updates
from .clean_tab import CleanTab
from .drivers_tab import DriversTab
from .dupes_tab import DupesTab
from .software_tab import SoftwareTab
from .startup_tab import StartupTab
from .uninstall_tab import UninstallTab

ROOT = Path(__file__).resolve().parents[2]


class App(tk.Tk):
    def __init__(self, rules_file: str):
        super().__init__()
        self.title("Woof Cleaner")
        self.geometry("1120x700")
        self.minsize(900, 560)
        if paths.ICON.exists():
            try:
                self.iconbitmap(default=str(paths.ICON))
            except tk.TclError:
                pass
        self._q: queue.Queue = queue.Queue()
        self._style()

        top = tk.Frame(self, bg=ACCENT)
        top.pack(fill="x")
        tk.Label(top, text="\U0001F436  Woof Cleaner", bg=ACCENT, fg="white",
                 font=("Segoe UI", 16, "bold")).pack(side="left", padx=14, pady=8)
        tk.Label(top, text=f"v{__version__}", bg=ACCENT, fg="#ffe9d6", font=("Segoe UI", 9)).pack(side="left", pady=(12, 0))
        admin = winutil.is_admin()
        tk.Label(top, text="Administrator" if admin else "Standard user", bg=ACCENT, fg="white",
                 font=("Segoe UI", 9, "bold")).pack(side="right", padx=14)
        if not admin:
            ttk.Button(top, text="Restart as administrator", command=self._elevate).pack(side="right", pady=6)
        ttk.Button(top, text="Check for updates", command=lambda: check_for_updates(self, manual=True)).pack(side="right", padx=6, pady=6)

        self.nb = ttk.Notebook(self, style="Side.TNotebook")
        self.nb.pack(fill="both", expand=True, padx=6, pady=6)
        self.tabs = [CleanTab(self.nb, self, rules_file), UninstallTab(self.nb, self), StartupTab(self.nb, self),
                     DupesTab(self.nb, self), SoftwareTab(self.nb, self), DriversTab(self.nb, self)]
        for t in self.tabs:
            self.nb.add(t, text=f"  {t.title}  ")
        self._shown: set[int] = set()
        self.nb.bind("<<NotebookTabChanged>>", self._tab_changed)

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", side="bottom")
        self.status = ttk.Label(bottom, text="Ready", anchor="w")
        self.status.pack(side="left", fill="x", expand=True, padx=8, pady=3)
        self.progress = ttk.Progressbar(bottom, mode="indeterminate", length=180)
        self.progress.pack(side="right", padx=8)
        self.after(80, self._pump)
        if selfupdate.auto_check_due():
            self.after(2500, lambda: check_for_updates(self, manual=False))

    def _style(self):
        s = ttk.Style(self)
        if "vista" in s.theme_names():
            s.theme_use("vista")
        s.configure("H1.TLabel", font=("Segoe UI", 13, "bold"))
        s.configure("Sub.TLabel", foreground="#555")
        s.configure("Big.TLabel", font=("Segoe UI", 11, "bold"), foreground=ACCENT)
        s.configure("Side.TNotebook", tabposition="wn")
        s.configure("Side.TNotebook.Tab", padding=(14, 10), font=("Segoe UI", 10), width=18)
        s.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))

    # ---- thread-safe UI calls
    def post(self, fn):
        self._q.put(fn)

    def _pump(self):
        try:
            while True:
                self._q.get_nowait()()
        except queue.Empty:
            pass
        self.after(80, self._pump)

    def set_status(self, msg: str):
        self.status.config(text=msg)

    def set_busy(self, busy: bool, label: str = ""):
        if busy:
            self.progress.start(12)
            self.set_status(label)
        else:
            self.progress.stop()

    def _tab_changed(self, _e):
        i = self.nb.index(self.nb.select())
        if i not in self._shown:
            self._shown.add(i)
            self.tabs[i].on_show()

    def _elevate(self):
        try:
            if paths.FROZEN:
                winutil.shell_execute(sys.executable, "", verb="runas", wait=False, cwd=str(paths.EXE_DIR))
            else:
                # Elevated processes don't inherit our environment (PYTHONPATH), so put ROOT on sys.path explicitly.
                code = f"import sys; sys.path.insert(0, r'{ROOT}'); from woofcleaner.cli import main; main(['gui'])"
                winutil.relaunch_as_admin(f'-c "{code}"', str(ROOT))
        except OSError as e:
            self.set_status(str(e))
            return
        self.destroy()


def launch(rules_file: str):
    App(rules_file).mainloop()
