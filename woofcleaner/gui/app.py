"""Woof Cleaner main window: a grouped sidebar of tools and one page per tool."""
from __future__ import annotations

import queue
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from .. import __version__, paths, scheduler, selfupdate, winutil
from .clean_tab import CleanTab
from .common import CheckImages
from .drivers_tab import DriversTab
from .dupes_tab import DupesTab
from .registry_tab import RegistryTab
from .schedule_tab import ScheduleTab
from .settings_tab import SettingsTab
from .software_tab import SoftwareTab
from .startup_tab import StartupPage
from .theme import Theme
from .uninstall_tab import UninstallTab
from .update_dialog import check_for_updates

ROOT = Path(__file__).resolve().parents[2]

NAV = [
    ("CLEAN", [CleanTab, RegistryTab, DupesTab]),
    ("SPEED UP", [StartupPage]),
    ("FIX & UPDATE", [SoftwareTab, DriversTab]),
    ("MANAGE", [UninstallTab, ScheduleTab]),
]


class NavItem(tk.Frame):
    def __init__(self, parent, app, icon: str, text: str, command):
        super().__init__(parent, cursor="hand2", height=40)
        self.app, self.command, self.active, self.hover = app, command, False, False
        t = app.theme
        self.bar = tk.Frame(self, width=3)
        self.bar.pack(side="left", fill="y", pady=8)
        self.icon = tk.Label(self, text=icon, font=t.fonts["icon"], width=2, anchor="center")
        self.icon.pack(side="left", padx=(14, 8))
        self.label = tk.Label(self, text=text, font=t.fonts["body"], anchor="w")
        self.label.pack(side="left", fill="x", expand=True, pady=9)
        for w in (self, self.icon, self.label):
            w.bind("<Button-1>", lambda _e: self.command())
            w.bind("<Enter>", lambda _e: self._hover(True))
            w.bind("<Leave>", lambda _e: self._hover(False))
        self.recolor()
        t.on_change(self.recolor)

    def _hover(self, on: bool):
        self.hover = on
        self.recolor()

    def set_active(self, on: bool):
        self.active = on
        self.recolor()

    def recolor(self):
        c, f = self.app.theme.c, self.app.theme.fonts
        bg = c["side_active"] if self.active else c["side_hover"] if self.hover else c["sidebar"]
        fg = c["side_active_text"] if self.active else c["side_text"]
        for w in (self, self.icon, self.label):
            w.configure(bg=bg)
        self.icon.configure(fg=c["accent"] if self.active else c["side_muted"] if not self.hover else c["side_text"])
        self.label.configure(fg=fg, font=f["semibold"] if self.active else f["body"])
        self.bar.configure(bg=c["accent"] if self.active else bg)


class App(tk.Tk):
    def __init__(self, rules_file: str):
        super().__init__()
        self.withdraw()
        self.title("Woof Cleaner")
        self.geometry("1240x780")
        self.minsize(1020, 640)
        if paths.ICON.exists():
            try:
                self.iconbitmap(default=str(paths.ICON))
            except tk.TclError:
                pass
        self._q: queue.Queue = queue.Queue()
        self.theme = Theme(self)
        self.check_images = CheckImages(self.theme)
        self.rules_file = rules_file
        self.is_admin = winutil.is_admin()

        self.sidebar = tk.Frame(self, width=240)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        self.theme.paint(self.sidebar, bg="sidebar")
        self.divider = tk.Frame(self, width=1)
        self.divider.pack(side="left", fill="y")
        self.theme.paint(self.divider, bg="border")

        main = ttk.Frame(self)
        main.pack(side="left", fill="both", expand=True)
        self._statusbar(main)   # packed before the content so it always keeps its row
        self.content = ttk.Frame(main)
        self.content.pack(fill="both", expand=True)
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)

        self.pages: list = []
        self.nav: list[NavItem] = []
        self._brand()
        for section, classes in NAV:
            self._section(section)
            for cls in classes:
                self._add_page(cls, rules_file if cls is CleanTab else None)
        spacer = tk.Frame(self.sidebar, height=1)
        spacer.pack(fill="both", expand=True)
        self.theme.paint(spacer, bg="sidebar")
        self._add_page(SettingsTab, None)
        self._footer()

        self._shown: set[int] = set()
        self.current = -1
        self.show(0)
        for n in range(min(9, len(self.pages))):
            self.bind_all(f"<Control-Key-{n + 1}>", lambda _e, n=n: self.show(n))
        self.after(80, self._pump)
        self.deiconify()
        self.theme.title_bar(self)
        if selfupdate.auto_check_due():
            self.after(2500, lambda: check_for_updates(self, manual=False))

    # ---- sidebar
    def _brand(self):
        f = tk.Frame(self.sidebar)
        f.pack(fill="x", padx=18, pady=(20, 14))
        self.theme.paint(f, bg="sidebar")
        self.logo = None
        if paths.LOGO.exists():
            try:
                self.logo = tk.PhotoImage(file=str(paths.LOGO))
            except tk.TclError:
                self.logo = None
        if self.logo:
            self.theme.paint(tk.Label(f, image=self.logo), bg="sidebar").pack(side="left")
        txt = tk.Frame(f)
        txt.pack(side="left", padx=(10, 0))
        self.theme.paint(txt, bg="sidebar")
        self.theme.paint(tk.Label(txt, text="Woof Cleaner", font=self.theme.fonts["brand"]),
                         bg="sidebar", fg="text").pack(anchor="w")
        self.theme.paint(tk.Label(txt, text=f"PC toolkit  ·  v{__version__}", font=self.theme.fonts["small"]),
                         bg="sidebar", fg="side_muted").pack(anchor="w")

    def _section(self, text: str):
        lbl = tk.Label(self.sidebar, text=text, font=self.theme.fonts["label"], anchor="w")
        lbl.pack(fill="x", padx=20, pady=(14, 4))
        self.theme.paint(lbl, bg="sidebar", fg="side_muted")

    def _add_page(self, cls, rules_file):
        page = cls(self.content, self, rules_file) if rules_file else cls(self.content, self)
        page.grid(row=0, column=0, sticky="nsew")
        n = len(self.pages)
        self.pages.append(page)
        item = NavItem(self.sidebar, self, page.icon, page.title, lambda n=n: self.show(n))
        item.pack(fill="x", padx=10, pady=1)
        self.nav.append(item)

    def _footer(self):
        f = tk.Frame(self.sidebar)
        f.pack(fill="x", padx=12, pady=(6, 16))
        self.theme.paint(f, bg="sidebar")
        chip = tk.Frame(f, padx=12, pady=10)
        chip.pack(fill="x")
        self.theme.paint(chip, bg="surface2")
        top = tk.Frame(chip)
        top.pack(fill="x")
        self.theme.paint(top, bg="surface2")
        self.theme.paint(tk.Label(top, text="", font=self.theme.fonts["icon"]), bg="surface2",
                         fg="good" if self.is_admin else "warn").pack(side="left")
        self.theme.paint(tk.Label(top, text="Administrator" if self.is_admin else "Standard user",
                                  font=self.theme.fonts["semibold"]), bg="surface2", fg="text").pack(side="left", padx=6)
        if not self.is_admin:
            link = tk.Label(chip, text="Restart as administrator  ›", font=self.theme.fonts["small"], cursor="hand2")
            link.pack(anchor="w", pady=(4, 0))
            self.theme.paint(link, bg="surface2", fg="accent")
            link.bind("<Button-1>", lambda _e: self.elevate())
        else:
            self.theme.paint(tk.Label(chip, text="All tools are unlocked", font=self.theme.fonts["small"]),
                             bg="surface2", fg="muted").pack(anchor="w", pady=(4, 0))

    def _statusbar(self, parent):
        bar = ttk.Frame(parent)
        bar.pack(fill="x", side="bottom")
        ttk.Separator(bar).pack(fill="x")
        inner = ttk.Frame(bar, padding=(28, 6))
        inner.pack(fill="x")
        self.status = ttk.Label(inner, text="Ready", style="Muted.TLabel", anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(inner, mode="indeterminate", length=160, style="Thin.Horizontal.TProgressbar")

    # ---- navigation
    def show(self, n: int):
        if n == self.current:
            return
        self.current = n
        for i, item in enumerate(self.nav):
            item.set_active(i == n)
        self.pages[n].tkraise()
        if n not in self._shown:
            self._shown.add(n)
            self.pages[n].on_show()

    def show_page(self, cls):
        for n, p in enumerate(self.pages):
            if isinstance(p, cls):
                self.show(n)
                return p
        return None

    # ---- thread-safe UI calls
    def post(self, fn):
        self._q.put(fn)

    def _pump(self):
        try:
            while True:
                self._q.get_nowait()()
        except queue.Empty:
            pass
        self.after(60, self._pump)

    def set_status(self, msg: str):
        self.status.config(text=msg)

    def set_busy(self, busy: bool, label: str = ""):
        if busy:
            self.progress.pack(side="right")
            self.progress.start(12)
            self.set_status(label)
        else:
            self.progress.stop()
            self.progress.pack_forget()

    def elevate(self):
        try:
            if scheduler.elevated_launch_enabled() and scheduler.start_elevated():
                pass
            elif paths.FROZEN:
                winutil.shell_execute(sys.executable, "gui --elevated-launch", verb="runas", wait=False,
                                      cwd=str(paths.EXE_DIR))
            else:
                # Elevated processes don't inherit our environment (PYTHONPATH), so put ROOT on sys.path explicitly.
                code = (f"import sys; sys.path.insert(0, r'{ROOT}'); from woofcleaner.cli import main; "
                        "main(['gui', '--elevated-launch'])")
                winutil.relaunch_as_admin(f'-c "{code}"', str(ROOT))
        except OSError as e:
            self.set_status(str(e))
            return
        self.destroy()


def launch(rules_file: str):
    App(rules_file).mainloop()
