"""Registry cleaner page: scan categories, review, back up and fix; restore any backup."""
from __future__ import annotations

from tkinter import filedialog, messagebox, ttk

from .. import regscan, winutil
from ..paths import BACKUP_DIR
from .common import BaseTab, Table, confirm, heading, stat_row, toolbar


class RegistryTab(BaseTab):
    title = "Registry"
    icon = ""

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.issues: list[regscan.Issue] = []
        head = heading(self, "Registry Cleaner", "Finds registry entries that point to programs, files and folders "
                       "that no longer exist. Everything is backed up before it is changed, and any backup can be "
                       "restored.")
        head.pack(fill="x")
        self.btn_fix = ttk.Button(head.actions, text="Fix selected issues", style="Accent.TButton", command=self.fix)
        self.btn_fix.pack(side="right")
        self.btn_fix.state(["disabled"])
        ttk.Button(head.actions, text="Scan for issues", command=self.scan).pack(side="right", padx=8)

        bar = toolbar(self)
        ttk.Button(bar, text="Restore a backup ...", command=self.restore).pack(side="left")
        ttk.Button(bar, text="Open backup folder", style="Ghost.TButton",
                   command=lambda: (BACKUP_DIR.mkdir(parents=True, exist_ok=True),
                                    winutil.shell_execute("explorer.exe", f'"{BACKUP_DIR}"', wait=False))
                   ).pack(side="left", padx=6)
        ttk.Button(bar, text="Select none", style="Ghost.TButton", command=lambda: self.table.set_all(False)).pack(side="right")
        ttk.Button(bar, text="Select all", style="Ghost.TButton", command=lambda: self.table.set_all(True)).pack(side="right")

        self.cards = stat_row(self, [("Issues found", True), ("Selected", False), ("Need administrator", False)])

        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)
        self.cats = Table(paned, [], tree_heading="Look for", selectmode="browse")
        self.cats.tree.column("#0", width=230)
        paned.add(self.cats, weight=1)
        for cat, (title, _desc) in regscan.CATEGORIES.items():
            self.cats.add(iid=cat, text=title, check=True)

        right = ttk.Frame(paned)
        paned.add(right, weight=4)
        self.after(50, lambda: paned.sashpos(0, 250))
        self.desc = ttk.Label(right, text="Press Scan for issues. Nothing is changed until you press Fix.",
                              style="Muted.TLabel", wraplength=700)
        self.desc.pack(side="bottom", anchor="w", padx=(10, 0), pady=(8, 0))
        self.table = Table(right, [("key", "Registry location", 420, "w")], tree_heading="Problem",
                           on_toggle=self._counts)
        self.table.tree.column("#0", width=420)
        self.table.pack(fill="both", expand=True, padx=(10, 0))
        self.table.tree.bind("<<TreeviewSelect>>", self._describe)

    def on_show(self):
        self.scan()

    def scan(self):
        cats = self.cats.checked()
        if not cats:
            messagebox.showinfo("Woof Cleaner", "Tick at least one category on the left.", parent=self)
            return
        self.run_bg(lambda: regscan.scan(cats, self.status), self._loaded, "Scanning the registry ...")

    def _loaded(self, issues):
        self.issues = issues
        self.table.clear()
        admin = winutil.is_admin()
        for cat, (title, _d) in regscan.CATEGORIES.items():
            mine = [(n, i) for n, i in enumerate(issues) if i.category == cat]
            if not mine:
                continue
            g = self.table.group(iid=f"cat:{cat}", text=f"{title}  ({len(mine)})")
            for n, i in mine:
                locked = i.needs_admin and not admin
                self.table.add(iid=str(n), text=i.problem + ("  ·  needs admin" if locked else ""),
                               values=(i.location,), parent=g, check=not locked, tags=("muted",) if locked else ())
        self._counts()
        self.btn_fix.state(["!disabled"] if issues else ["disabled"])
        self.app.set_status(f"{len(issues)} registry issue(s) found" if issues else "No registry issues found")
        if not issues:
            self.desc.config(text="No issues found. Your registry is in good shape.")

    def _counts(self):
        sel = self._selected()
        self.cards[0].set(str(len(self.issues)), "in " + str(len({i.category for i in self.issues})) + " categories")
        self.cards[1].set(str(len(sel)), "will be fixed")
        need = sum(i.needs_admin for i in self.issues)
        self.cards[2].set(str(need), "restart as administrator to fix" if need and not winutil.is_admin() else "")

    def _selected(self) -> list[regscan.Issue]:
        return [self.issues[int(k)] for k in self.table.checked() if k.isdigit()]

    def _describe(self, _e=None):
        sel = self.table.tree.selection()
        if not sel:
            return
        k = sel[0]
        cat = k[4:] if k.startswith("cat:") else self.issues[int(k)].category
        title, desc = regscan.CATEGORIES[cat]
        self.desc.config(text=f"{title}: {desc}")

    def fix(self):
        sel = self._selected()
        if not sel:
            messagebox.showinfo("Woof Cleaner", "Tick the issues to fix.", parent=self)
            return
        if not confirm(self, "Fix registry issues", f"Back up and fix {len(sel)} registry issue(s)?\n\n"
                       "A backup file is written first; use 'Restore a backup' to undo."):
            return
        self.run_bg(lambda: regscan.fix(sel, BACKUP_DIR), self._fixed, "Fixing registry issues ...")

    def _fixed(self, result):
        fixed, errors, backup = result
        msg = f"Fixed {fixed} issue(s)."
        if backup:
            msg += f"\n\nBackup: {backup}"
        if errors:
            msg += "\n\nNot fixed:\n" + "\n".join(errors[:10])
        (messagebox.showwarning if errors else messagebox.showinfo)("Woof Cleaner", msg, parent=self)
        self.scan()

    def restore(self):
        files = regscan.list_backups(BACKUP_DIR)
        f = filedialog.askopenfilename(parent=self, title="Restore a registry backup",
                                       initialdir=str(BACKUP_DIR if BACKUP_DIR.exists() else "."),
                                       filetypes=[("Woof Cleaner backups", "*.json")],
                                       initialfile=files[0].name if files else "")
        if not f:
            return
        if not confirm(self, "Restore backup", f"Write this backup back into the registry?\n\n{f}"):
            return
        from pathlib import Path
        n, errors = regscan.restore(Path(f))
        msg = f"Restored {n} item(s)." + ("\n\nErrors:\n" + "\n".join(errors[:10]) if errors else "")
        (messagebox.showwarning if errors else messagebox.showinfo)("Woof Cleaner", msg, parent=self)
