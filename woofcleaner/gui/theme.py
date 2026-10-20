"""Light / dark theme for the Tk GUI: palette, fonts, ttk styles, Windows title-bar colour.

ttk widgets follow the styles configured here. Plain tk widgets (sidebar, cards, text boxes) register with
Theme.paint(widget, bg=..., fg=...) using palette keys, so a theme switch can recolour them.
"""
from __future__ import annotations

import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from .. import settings

PALETTES = {
    "light": {
        "bg": "#f3f4f7", "surface": "#ffffff", "surface2": "#eef0f4", "hover": "#e6e9ef", "border": "#dfe2e8",
        "button": "#ffffff", "btn_border": "#cdd2db", "btn_hover": "#f1f3f7",
        "text": "#1b2130", "muted": "#677086", "faint": "#a3aabb",
        "accent": "#e2772b", "accent_hover": "#cb6420", "accent_press": "#b25719", "accent_text": "#ffffff",
        "accent_soft": "#fdeee3", "select": "#fbe0cc",
        "sidebar": "#ffffff", "side_hover": "#f3f4f7", "side_active": "#fdeee3", "side_text": "#3a4152",
        "side_muted": "#8a92a5", "side_active_text": "#c25e17",
        "good": "#15803d", "good_soft": "#dcfce7", "warn": "#b45309", "warn_soft": "#fef3c7",
        "bad": "#c62828", "bad_soft": "#fde2e2",
    },
    "dark": {
        "bg": "#14161b", "surface": "#1c1f26", "surface2": "#252932", "hover": "#2c313b", "border": "#2f343e",
        "button": "#2a2e38", "btn_border": "#3b404c", "btn_hover": "#343945",
        "text": "#e7e9ef", "muted": "#9aa2b4", "faint": "#5f6778",
        "accent": "#f08a3e", "accent_hover": "#f59c57", "accent_press": "#d97526", "accent_text": "#1a1206",
        "accent_soft": "#3a2717", "select": "#4a3020",
        "sidebar": "#0f1115", "side_hover": "#1a1d23", "side_active": "#2a1e14", "side_text": "#c3c8d4",
        "side_muted": "#6c7487", "side_active_text": "#f5a262",
        "good": "#4ade80", "good_soft": "#123322", "warn": "#fbbf24", "warn_soft": "#3a2c0c",
        "bad": "#f87171", "bad_soft": "#3b1717",
    },
}


def system_prefers_dark() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def _pick(families: set[str], *names: str) -> str:
    return next((n for n in names if n in families), names[-1])


class Theme:
    def __init__(self, root: tk.Tk):
        self.root = root
        fam = set(tkfont.families(root))
        body = _pick(fam, "Segoe UI Variable Text", "Segoe UI")
        semibold = _pick(fam, "Segoe UI Variable Text Semibold", "Segoe UI Semibold", "Segoe UI")
        display = _pick(fam, "Segoe UI Variable Display Semib", "Segoe UI Semibold", "Segoe UI")
        self.icon_family = _pick(fam, "Segoe Fluent Icons", "Segoe MDL2 Assets", "Segoe UI Symbol")
        self.fonts = {
            "body": (body, 10), "small": (body, 9), "semibold": (semibold, 10), "title": (display, 20),
            "h2": (semibold, 12), "stat": (display, 22), "label": (semibold, 9), "brand": (display, 14),
            "mono": ("Cascadia Mono" if "Cascadia Mono" in fam else "Consolas", 9),
            "icon": (self.icon_family, 13), "icon_big": (self.icon_family, 20),
        }
        # named fonts, not option_add("*Font"): that would also override the font of every ttk style
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont"):
            try:
                tkfont.nametofont(name, root).configure(family=body, size=10)
            except tk.TclError:
                pass
        self.mode = settings.get("theme", "auto")
        self.name = "light"
        self.c: dict[str, str] = PALETTES["light"]
        self._painted: list[tuple[tk.Misc, dict]] = []
        self._listeners: list = []
        self.style = ttk.Style(root)
        self.style.theme_use("clam")
        self.apply(self.mode, save=False)

    # ---- public
    def apply(self, mode: str, save: bool = True) -> None:
        self.mode = mode
        self.name = ("dark" if system_prefers_dark() else "light") if mode == "auto" else mode
        self.c = PALETTES[self.name]
        if save:
            settings.save(theme=mode)
        self._configure_styles()
        self.root.configure(bg=self.c["bg"])
        alive = []
        for w, roles in self._painted:
            try:
                self._paint_one(w, roles)
                alive.append((w, roles))
            except tk.TclError:
                pass
        self._painted = alive
        for fn in list(self._listeners):
            fn()
        self.title_bar(self.root)

    def paint(self, widget, **roles):
        """Colour a plain tk widget from palette keys (bg=, fg=, activebackground=, ...); kept on theme change."""
        self._paint_one(widget, roles)
        self._painted.append((widget, roles))
        return widget

    def on_change(self, fn) -> None:
        self._listeners.append(fn)

    def title_bar(self, win) -> None:
        """Dark or light Windows title bar (DWMWA_USE_IMMERSIVE_DARK_MODE)."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            win.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
            val = ctypes.c_int(1 if self.name == "dark" else 0)
            for attr in (20, 19):   # 20 on Windows 10 2004+ / 11, 19 on older builds
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), 4) == 0:
                    break
            # caption colour on Windows 11 (DWMWA_CAPTION_COLOR = 35): match the window background
            bg = self.c["sidebar"].lstrip("#")
            colorref = ctypes.c_int(int(bg[4:6] + bg[2:4] + bg[0:2], 16))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(colorref), 4)
        except (OSError, AttributeError, tk.TclError):
            pass

    # ---- internals
    def _paint_one(self, w, roles):
        w.configure(**{k: self.c.get(v, v) for k, v in roles.items()})

    def _configure_styles(self):
        c, f, s = self.c, self.fonts, self.style
        s.configure(".", background=c["bg"], foreground=c["text"], font=f["body"], bordercolor=c["border"],
                    lightcolor=c["border"], darkcolor=c["border"], troughcolor=c["surface2"],
                    focuscolor=c["accent"], selectbackground=c["select"], selectforeground=c["text"],
                    insertcolor=c["text"], fieldbackground=c["surface"])
        s.map(".", foreground=[("disabled", c["faint"])])

        # frames & labels
        for name, bg in (("TFrame", c["bg"]), ("Card.TFrame", c["surface"]), ("Side.TFrame", c["sidebar"])):
            s.configure(name, background=bg)
        s.configure("Card.TFrame", relief="solid", borderwidth=1, bordercolor=c["border"])
        s.configure("Plain.TFrame", background=c["surface"])
        s.configure("TLabel", background=c["bg"], foreground=c["text"])
        s.configure("Card.TLabel", background=c["surface"], foreground=c["text"])
        s.configure("CardMuted.TLabel", background=c["surface"], foreground=c["muted"], font=f["small"])
        s.configure("CardTitle.TLabel", background=c["surface"], foreground=c["text"], font=f["h2"])
        s.configure("Stat.TLabel", background=c["surface"], foreground=c["text"], font=f["stat"])
        s.configure("StatAccent.TLabel", background=c["surface"], foreground=c["accent"], font=f["stat"])
        s.configure("H1.TLabel", font=f["title"], foreground=c["text"])
        s.configure("H2.TLabel", font=f["h2"], foreground=c["text"])
        s.configure("Sub.TLabel", foreground=c["muted"])
        s.configure("Muted.TLabel", foreground=c["muted"], font=f["small"])
        s.configure("Big.TLabel", font=f["h2"], foreground=c["accent"])
        s.configure("Good.TLabel", foreground=c["good"], font=f["semibold"])
        s.configure("Warn.TLabel", foreground=c["warn"], font=f["semibold"])
        s.configure("Bad.TLabel", foreground=c["bad"], font=f["semibold"])

        # buttons
        # clam draws the 1px bordercolor outline only for raised/sunken reliefs; light/dark = face keeps it flat
        s.configure("TButton", background=c["button"], foreground=c["text"], bordercolor=c["btn_border"],
                    lightcolor=c["button"], darkcolor=c["button"], relief="raised", padding=(14, 7),
                    focusthickness=0, focuscolor=c["button"], font=f["body"])
        s.map("TButton", background=[("disabled", c["surface2"]), ("pressed", c["hover"]), ("active", c["btn_hover"])],
              lightcolor=[("disabled", c["surface2"]), ("active", c["btn_hover"])],
              darkcolor=[("disabled", c["surface2"]), ("active", c["btn_hover"])],
              bordercolor=[("disabled", c["border"]), ("active", c["faint"])], focuscolor=[("active", c["btn_hover"])],
              relief=[("pressed", "sunken")])
        s.configure("Accent.TButton", background=c["accent"], foreground=c["accent_text"], bordercolor=c["accent"],
                    lightcolor=c["accent"], darkcolor=c["accent"], focuscolor=c["accent"], font=f["semibold"])
        s.map("Accent.TButton",
              background=[("disabled", c["surface2"]), ("pressed", c["accent_press"]), ("active", c["accent_hover"])],
              lightcolor=[("pressed", c["accent_press"]), ("active", c["accent_hover"])],
              darkcolor=[("pressed", c["accent_press"]), ("active", c["accent_hover"])],
              bordercolor=[("disabled", c["border"]), ("active", c["accent_hover"])],
              focuscolor=[("active", c["accent_hover"])], foreground=[("disabled", c["faint"])])
        s.configure("Danger.TButton", background=c["button"], foreground=c["bad"], bordercolor=c["btn_border"],
                    lightcolor=c["button"], darkcolor=c["button"], focuscolor=c["button"])
        s.map("Danger.TButton", background=[("pressed", c["bad_soft"]), ("active", c["bad_soft"])],
              lightcolor=[("active", c["bad_soft"])], darkcolor=[("active", c["bad_soft"])],
              bordercolor=[("active", c["bad"])], focuscolor=[("active", c["bad_soft"])])
        s.configure("Ghost.TButton", background=c["bg"], bordercolor=c["bg"], lightcolor=c["bg"], darkcolor=c["bg"],
                    focuscolor=c["bg"], foreground=c["accent"], padding=(8, 5), width=0, relief="flat")
        s.map("Ghost.TButton", background=[("active", c["surface2"])], bordercolor=[("active", c["surface2"])],
              lightcolor=[("active", c["surface2"])], darkcolor=[("active", c["surface2"])],
              focuscolor=[("active", c["surface2"])])

        # check / radio
        for w in ("TCheckbutton", "TRadiobutton"):
            s.configure(w, background=c["bg"], foreground=c["text"], indicatorbackground=c["surface"],
                        indicatorforeground=c["accent_text"], indicatorrelief="flat", indicatormargin=(0, 0, 6, 0),
                        upperbordercolor=c["faint"], lowerbordercolor=c["faint"], focuscolor=c["bg"])
            s.map(w, indicatorbackground=[("selected", c["accent"]), ("active", c["surface2"])],
                  background=[("active", c["bg"])], upperbordercolor=[("selected", c["accent"])],
                  lowerbordercolor=[("selected", c["accent"])])
        s.configure("Card.TCheckbutton", background=c["surface"], focuscolor=c["surface"])
        s.map("Card.TCheckbutton", background=[("active", c["surface"])])
        s.configure("Card.TRadiobutton", background=c["surface"], focuscolor=c["surface"])
        s.map("Card.TRadiobutton", background=[("active", c["surface"])])

        # inputs
        for w in ("TEntry", "TCombobox", "TSpinbox"):
            s.configure(w, fieldbackground=c["surface"], foreground=c["text"], bordercolor=c["border"],
                        lightcolor=c["surface"], darkcolor=c["surface"], arrowcolor=c["muted"], padding=(8, 5),
                        background=c["surface"], insertcolor=c["text"])
            s.map(w, bordercolor=[("focus", c["accent"]), ("hover", c["faint"])],
                  lightcolor=[("focus", c["accent"])], fieldbackground=[("readonly", c["surface"])],
                  foreground=[("readonly", c["text"])], background=[("active", c["surface2"])],
                  arrowcolor=[("active", c["text"])])
        self.root.option_add("*TCombobox*Listbox.background", c["surface"])
        self.root.option_add("*TCombobox*Listbox.foreground", c["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", c["select"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", c["text"])
        self.root.option_add("*TCombobox*Listbox.font", f["body"])

        # tables
        s.configure("Treeview", background=c["surface"], fieldbackground=c["surface"], foreground=c["text"],
                    rowheight=30, borderwidth=0, relief="flat", font=f["body"])
        s.map("Treeview", background=[("selected", c["select"])], foreground=[("selected", c["text"])])
        s.configure("Treeview.Heading", background=c["surface"], foreground=c["muted"], font=f["label"],
                    relief="flat", borderwidth=0, padding=(8, 8), lightcolor=c["surface"], darkcolor=c["border"],
                    bordercolor=c["border"])
        s.map("Treeview.Heading", background=[("active", c["surface2"])], foreground=[("active", c["text"])])
        s.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        s.configure("Table.TFrame", background=c["surface"], relief="solid", borderwidth=1, bordercolor=c["border"])

        # scrollbars: thin, flat
        for orient in ("Vertical", "Horizontal"):
            s.configure(f"{orient}.TScrollbar", background=c["surface2"], troughcolor=c["surface"],
                        bordercolor=c["surface"], lightcolor=c["surface2"], darkcolor=c["surface2"],
                        arrowcolor=c["faint"], relief="flat", gripcount=0, arrowsize=11)
            s.map(f"{orient}.TScrollbar", background=[("active", c["hover"]), ("pressed", c["faint"])],
                  lightcolor=[("active", c["hover"])], darkcolor=[("active", c["hover"])])

        # progress
        s.configure("TProgressbar", background=c["accent"], troughcolor=c["surface2"], bordercolor=c["surface2"],
                    lightcolor=c["accent"], darkcolor=c["accent"], thickness=4)
        s.configure("Thin.Horizontal.TProgressbar", thickness=3)

        # tabs (sub-pages): underline style
        s.configure("TNotebook", background=c["bg"], borderwidth=0, tabmargins=(0, 0, 0, 0))
        s.configure("TNotebook.Tab", background=c["bg"], foreground=c["muted"], padding=(16, 9), borderwidth=0,
                    font=f["semibold"], lightcolor=c["bg"], bordercolor=c["bg"], focuscolor=c["bg"])
        s.map("TNotebook.Tab", background=[("selected", c["surface"]), ("active", c["surface2"])],
              foreground=[("selected", c["accent"]), ("active", c["text"])],
              lightcolor=[("selected", c["accent"])], expand=[("selected", (0, 0, 0, 0))])

        s.configure("TPanedwindow", background=c["bg"])
        s.configure("Sash", sashthickness=8, gripcount=0, background=c["bg"], lightcolor=c["bg"], bordercolor=c["bg"])
        s.configure("TSeparator", background=c["border"])
        s.configure("TLabelframe", background=c["surface"], bordercolor=c["border"])
        s.configure("TLabelframe.Label", background=c["surface"], foreground=c["muted"], font=f["label"])
