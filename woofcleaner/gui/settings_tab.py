"""Settings page: appearance, cookie allowlist, start elevated without UAC, updates, about."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .. import __version__, paths, scheduler, selfupdate, settings, winutil
from .common import BaseTab, heading
from .update_dialog import check_for_updates

POPULAR = ["google.com", "youtube.com", "github.com", "microsoft.com", "live.com", "outlook.com", "office.com",
           "facebook.com", "instagram.com", "x.com", "linkedin.com", "reddit.com", "amazon.com", "netflix.com",
           "spotify.com", "discord.com", "whatsapp.com", "tokopedia.com", "shopee.co.id", "chatgpt.com", "claude.ai"]


class SettingsTab(BaseTab):
    title = "Settings"
    icon = ""

    def __init__(self, parent, app):
        super().__init__(parent, app)
        heading(self, "Settings", "Personalize Woof Cleaner.").pack(fill="x", pady=(0, 16))
        cols = ttk.Frame(self)
        cols.pack(fill="both", expand=True)
        cols.columnconfigure(0, weight=1, uniform="c")
        cols.columnconfigure(1, weight=1, uniform="c")
        left = ttk.Frame(cols)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        right = ttk.Frame(cols)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        # appearance
        card = self._card(left, "Appearance", "Choose how Woof Cleaner looks.")
        self.mode = tk.StringVar(value=app.theme.mode)
        row = ttk.Frame(card, style="Plain.TFrame")
        row.pack(anchor="w", pady=(6, 0))
        for value, label in (("auto", "Match Windows"), ("light", "Light"), ("dark", "Dark")):
            ttk.Radiobutton(row, text=label, value=value, variable=self.mode, style="Card.TRadiobutton",
                            command=lambda: app.theme.apply(self.mode.get())).pack(side="left", padx=(0, 18))

        # administrator
        card = self._card(left, "Administrator rights", "Some tools (Windows temp folders, HKLM registry entries, "
                          "services, drivers) need administrator rights.")
        self.elev = tk.BooleanVar(value=scheduler.elevated_launch_enabled())
        cb = ttk.Checkbutton(card, text="Always start as administrator, without the UAC prompt", variable=self.elev,
                             style="Card.TCheckbutton", command=self._toggle_elev)
        cb.pack(anchor="w", pady=(6, 0))
        hint = ("Uses a Task Scheduler task with highest privileges."
                if winutil.is_admin() else "Restart as administrator to change this.")
        ttk.Label(card, text=hint, style="CardMuted.TLabel").pack(anchor="w", pady=(4, 0))
        if not winutil.is_admin():
            cb.state(["disabled"])

        # updates
        card = self._card(left, "Updates", f"You have Woof Cleaner {__version__}.")
        self.auto = tk.BooleanVar(value=selfupdate.load_settings().get("auto_check", True))
        ttk.Checkbutton(card, text="Check for updates automatically", variable=self.auto, style="Card.TCheckbutton",
                        command=lambda: selfupdate.save_settings(auto_check=self.auto.get())).pack(anchor="w", pady=(6, 8))
        ttk.Button(card, text="Check for updates now", command=lambda: check_for_updates(app, manual=True)).pack(anchor="w")

        # about
        card = self._card(left, "Data", "Settings, logs and every backup are stored here.")
        ttk.Label(card, text=str(paths.USER_DIR), style="CardMuted.TLabel").pack(anchor="w", pady=(4, 8))
        b = ttk.Frame(card, style="Plain.TFrame")
        b.pack(anchor="w")
        ttk.Button(b, text="Open data folder", command=lambda: self._open(paths.USER_DIR)).pack(side="left")
        ttk.Button(b, text="Open backups", command=lambda: self._open(paths.BACKUP_DIR)).pack(side="left", padx=8)

        # cookie allowlist
        card = self._card(right, "Cookie allowlist", "Cookies from these websites are kept when browser cookies are "
                          "cleaned, so you stay signed in. Subdomains are included.", expand=True)
        add = ttk.Frame(card, style="Plain.TFrame")
        add.pack(fill="x", pady=(8, 8))
        self.new_site = tk.StringVar()
        e = ttk.Entry(add, textvariable=self.new_site)
        e.pack(side="left", fill="x", expand=True)
        e.bind("<Return>", lambda _e: self._add_site())
        ttk.Button(add, text="Add", style="Accent.TButton", command=self._add_site).pack(side="left", padx=(8, 0))
        box = ttk.Frame(card, style="Plain.TFrame")
        box.pack(fill="both", expand=True)
        self.sites = tk.Listbox(box, activestyle="none", relief="flat", borderwidth=0, highlightthickness=1,
                                selectmode="extended", font=app.theme.fonts["body"])
        app.theme.paint(self.sites, bg="surface", fg="text", selectbackground="select", selectforeground="text",
                        highlightbackground="border", highlightcolor="accent")
        sb = ttk.Scrollbar(box, orient="vertical", command=self.sites.yview)
        self.sites.configure(yscrollcommand=sb.set)
        self.sites.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        btns = ttk.Frame(card, style="Plain.TFrame")
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="Remove selected", style="Danger.TButton", command=self._remove_sites).pack(side="left")
        ttk.Button(btns, text="Add popular sites", command=self._add_popular).pack(side="right")
        self._load_sites()

    def _card(self, parent, title: str, sub: str, expand: bool = False) -> ttk.Frame:
        card = ttk.Frame(parent, style="Card.TFrame", padding=(18, 14))
        card.pack(fill="both" if expand else "x", expand=expand, pady=(0, 12))
        ttk.Label(card, text=title, style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(card, text=sub, style="CardMuted.TLabel", wraplength=440, justify="left").pack(anchor="w", pady=(2, 0))
        return card

    @staticmethod
    def _open(p):
        p.mkdir(parents=True, exist_ok=True)
        winutil.shell_execute("explorer.exe", f'"{p}"', wait=False)

    def _toggle_elev(self):
        try:
            scheduler.set_elevated_launch(self.elev.get())
        except OSError as e:
            self.elev.set(not self.elev.get())
            messagebox.showerror("Woof Cleaner", str(e), parent=self)

    # ---- allowlist
    def _load_sites(self):
        self.sites.delete(0, "end")
        for d in sorted(settings.cookie_allowlist()):
            self.sites.insert("end", d)

    def _save_sites(self, items):
        settings.save(cookie_allowlist=sorted({settings.normalise_domain(d) for d in items if d.strip()}))
        self._load_sites()

    def _add_site(self):
        d = settings.normalise_domain(self.new_site.get())
        if not d or "." not in d:
            messagebox.showinfo("Woof Cleaner", "Type a website such as example.com", parent=self)
            return
        self._save_sites(settings.cookie_allowlist() + [d])
        self.new_site.set("")

    def _remove_sites(self):
        gone = {self.sites.get(i) for i in self.sites.curselection()}
        self._save_sites([d for d in settings.cookie_allowlist() if d not in gone])

    def _add_popular(self):
        self._save_sites(settings.cookie_allowlist() + POPULAR)
