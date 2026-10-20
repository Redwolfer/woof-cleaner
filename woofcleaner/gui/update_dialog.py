"""'A new version is available' dialog + download/verify/apply flow."""
from __future__ import annotations

import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from .. import __version__, selfupdate
from ..engine import human


def check_for_updates(app, manual: bool) -> None:
    """Background check; shows the dialog when a newer release exists. Silent on errors unless manual."""
    def work():
        try:
            rel = selfupdate.check()
        except Exception as e:  # network down, rate limit, no repo configured...
            if manual:
                app.post(lambda: messagebox.showerror("Woof Cleaner", f"Could not check for updates:\n{e}", parent=app))
            return
        if rel is None:
            if manual:
                app.post(lambda: messagebox.showinfo("Woof Cleaner", f"You have the latest version ({__version__}).", parent=app))
            return
        if not manual and selfupdate.load_settings().get("skip_version") == rel.version:
            return
        app.post(lambda: UpdateDialog(app, rel))

    threading.Thread(target=work, daemon=True).start()


class UpdateDialog(tk.Toplevel):
    def __init__(self, app, rel: selfupdate.Release):
        super().__init__(app)
        self.app, self.rel = app, rel
        self.title("Update available")
        self.geometry("560x420")
        self.transient(app)
        self.grab_set()
        app.theme.paint(self, bg="bg")
        ttk.Label(self, text=f"Woof Cleaner {rel.version} is available", style="H1.TLabel").pack(anchor="w", padx=14, pady=(12, 2))
        ttk.Label(self, text=f"You have {__version__}.", style="Sub.TLabel").pack(anchor="w", padx=14)
        notes = tk.Text(self, height=12, wrap="word", font=app.theme.fonts["body"], relief="flat", padx=10, pady=8,
                        highlightthickness=1)
        app.theme.paint(notes, bg="surface", fg="text", highlightbackground="border", highlightcolor="border")
        notes.insert("1.0", rel.notes.strip() or "(no release notes)")
        notes.config(state="disabled")
        notes.pack(fill="both", expand=True, padx=14, pady=8)
        self.auto = tk.BooleanVar(value=selfupdate.load_settings().get("auto_check", True))
        ttk.Checkbutton(self, text="Check for updates automatically", variable=self.auto,
                        command=lambda: selfupdate.save_settings(auto_check=self.auto.get())).pack(anchor="w", padx=14)
        self.bar = ttk.Progressbar(self, mode="determinate")
        self.bar.pack(fill="x", padx=14, pady=6)
        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=14, pady=(0, 12))
        self.btn_now = ttk.Button(btns, text="Update now", style="Accent.TButton", command=self.update_now)
        self.btn_now.pack(side="right")
        ttk.Button(btns, text="Later", command=self.destroy).pack(side="right", padx=6)
        ttk.Button(btns, text="Skip this version", command=self.skip).pack(side="right")
        ttk.Button(btns, text="Release page", command=lambda: webbrowser.open(rel.page)).pack(side="left")

        kind = selfupdate.install_kind()
        self.asset = rel.setup if kind == "installed" else rel.portable if kind == "portable" else None
        if self.asset is None:
            self.btn_now.state(["disabled"])
            why = "Running from source - use git pull." if kind == "source" else "This release has no file for your copy."
            ttk.Label(self, text=why, style="Bad.TLabel").pack(anchor="w", padx=14)
        app.theme.title_bar(self)

    def skip(self):
        selfupdate.save_settings(skip_version=self.rel.version)
        self.destroy()

    def update_now(self):
        self.btn_now.state(["disabled"])

        def progress(done, total):
            if total:
                self.app.post(lambda: self.bar.config(value=done * 100 / total))

        def work():
            try:
                f = selfupdate.download(self.asset, progress)
                selfupdate.apply(self.rel, f)
            except Exception as e:  # show any failure; the current version keeps running
                err = e
                self.app.post(lambda: (messagebox.showerror("Woof Cleaner", f"Update failed:\n{err}", parent=self),
                                       self.btn_now.state(["!disabled"])))
                return
            self.app.post(self._restart)

        self.app.set_status(f"Downloading {self.asset.name} ({human(self.asset.size)}) ...")
        threading.Thread(target=work, daemon=True).start()

    def _restart(self):
        self.app.set_status("Installing the update - Woof Cleaner will restart ...")
        self.app.after(300, self.app.destroy)
