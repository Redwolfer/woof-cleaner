"""Edit the folder lists shared by manual and scheduled cleaning."""
import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .. import settings


def edit_folders(parent):
    dialog = tk.Toplevel(parent)
    dialog.title("Cleaning folders")
    dialog.transient(parent.winfo_toplevel())
    frame = ttk.Frame(dialog, padding=16)
    frame.pack(fill="both", expand=True)
    lists = {}
    changed = False

    def choose(key):
        folder = filedialog.askdirectory(parent=dialog, mustexist=True)
        if not folder:
            return
        folder = os.path.normpath(folder)
        if key == "included_folders" and len(Path(folder).parts) < 3:
            messagebox.showwarning("Cleaning folders", "Choose a deeper subfolder.", parent=dialog)
            return
        box = lists[key]
        if os.path.normcase(folder) not in {os.path.normcase(p) for p in box.get(0, "end")}:
            box.insert("end", folder)

    for key, title in (("included_folders", "Include when Custom folders is selected"),
                       ("excluded_folders", "Always skip these folders during file scans")):
        ttk.Label(frame, text=title).pack(anchor="w", pady=(8, 2))
        box = tk.Listbox(frame, width=60, height=4, exportselection=False)
        box.pack(fill="both", expand=True)
        lists[key] = box
        for folder in settings.get(key, []):
            box.insert("end", folder)
        bar = ttk.Frame(frame)
        bar.pack(fill="x")
        ttk.Button(bar, text="Add folder…", command=lambda k=key: choose(k)).pack(side="left")
        ttk.Button(bar, text="Remove", command=lambda b=box: b.delete(b.curselection()[0])
                   if b.curselection() else None).pack(side="left")

    def save():
        nonlocal changed
        settings.save(**{k: list(b.get(0, "end")) for k, b in lists.items()})
        changed = True
        dialog.destroy()

    ttk.Button(frame, text="Save folders", command=save).pack(anchor="e", pady=(12, 0))
    dialog.bind("<Escape>", lambda _: dialog.destroy())
    dialog.grab_set()
    parent.wait_window(dialog)
    return changed
