"""Read-only maintenance checks, disk usage and cleaning history."""
import threading
from tkinter import filedialog, ttk

from .. import settings, startup
from ..engine import Context, Mode, human, run
from ..reports import activity_totals, disk_usage
from ..rules import load_rules
from .clean_tab import CleanTab
from .common import BaseTab, Table, heading
from .startup_tab import StartupPage


class ReportsTab(BaseTab):
    title = "PC overview"
    icon = "▤"

    def __init__(self, parent, app):
        super().__init__(parent, app)
        heading(self, self.title).pack(fill="x", pady=(0, 8))
        book = ttk.Notebook(self)
        book.pack(fill="both", expand=True)
        self.cancel = threading.Event()
        for title, setup in (("Health Check", self._health_page), ("Disk usage", self._disk_page),
                             ("Statistics", self._stats_page)):
            page = ttk.Frame(book, padding=10)
            book.add(page, text=title)
            setup(page)
        book.bind("<<NotebookTabChanged>>", lambda _: self.refresh_stats())

    def _health_page(self, page):
        actions = ttk.Frame(page)
        actions.pack(fill="x")
        ttk.Button(actions, text="Scan selected rules", style="Accent.TButton", command=self.health).pack(side="left")
        ttk.Button(actions, text="Stop", command=self.cancel.set).pack(side="left", padx=6)
        self.score = ttk.Label(page, text="Scan your Custom Clean selection and review startup apps.")
        self.score.pack(anchor="w", pady=8)
        self.findings = Table(page, [("result", "Result", 240, "w")], tree_heading="Check")
        self.findings.pack(fill="both", expand=True)
        bar = ttk.Frame(page)
        bar.pack(fill="x", pady=(8, 0))
        for label, tool in (("Review in Custom Clean", CleanTab), ("Review startup apps", StartupPage)):
            ttk.Button(bar, text=label, command=lambda cls=tool: self.app.show_page(cls)).pack(side="left", padx=(0, 6))

    def health(self):
        if self.busy:
            return
        self.cancel.clear()
        self.findings.clear()
        self.score.config(text="Scanning…")
        def work():
            rs = load_rules(self.app.rules_file)
            selected = rs.selection(settings.get("clean_selection"))
            results = run(selected, Context(rs, mode=Mode.ANALYSE, cancel=self.cancel, progress=self.status))
            items = [] if self.cancel.is_set() else startup.list_items(include_tasks=False)
            return results, items

        def done(data):
            results, items = data
            checked = [r for r in results if r.applicable]
            clear = sum(not r.found_anything and not r.errors for r in checked)
            summary = f"{clear}/{len(checked)} applicable rules had no findings or errors."
            if not checked:
                summary = "No applicable rules selected."
            if self.cancel.is_set():
                summary = "Stopped. Partial findings are shown."
            self.score.config(text=summary)
            for r in checked:
                label = f"{r.files} files · {r.records} records · {r.reg_items} registry items · {human(r.bytes)}"
                node = self.findings.add(text=r.name, values=(label,), open=False)
                for note in dict.fromkeys(r.notes + r.errors):
                    self.findings.add(text=note, parent=node)
            if not self.cancel.is_set():
                self.findings.add(text="Startup apps", values=(f"{sum(i.enabled for i in items)} enabled",))
            self.app.set_status(summary)
        self.run_bg(work, done, "Scanning selected rules…")

    def _disk_page(self, page):
        bar = ttk.Frame(page)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Button(bar, text="Choose folder…", command=self.disk).pack(side="left")
        ttk.Button(bar, text="Stop", command=self.cancel.set).pack(side="left", padx=6)
        self.disk_result = ttk.Label(page, text="Choose a folder to measure its files by extension.")
        self.disk_result.pack(anchor="w", pady=(0, 8))
        self.sizes = Table(page, [("files", "Files", 100, "e"), ("bytes", "Space used", 120, "e")],
                           tree_heading="Extension / skipped path")
        self.sizes.pack(fill="both", expand=True)

    def disk(self):
        if self.busy:
            return
        root = filedialog.askdirectory(parent=self)
        if not root:
            return
        self.cancel.clear()
        self.sizes.clear()
        self.disk_result.config(text=root)
        skipped_paths = []

        def remember(path, reason):
            if len(skipped_paths) < 100:
                skipped_paths.append((path, reason))

        def done(result):
            sizes, counts, skipped = result
            for ext, size in sizes.most_common():
                self.sizes.add(text=ext, values=(counts[ext], human(size)))
            if skipped:
                group = self.sizes.add(text=f"Skipped entries ({len(skipped_paths)} of {skipped})", open=False)
                for path, reason in skipped_paths:
                    row = self.sizes.add(text=path, parent=group)
                    self.sizes.add(text=reason, parent=row)
            lead = "Stopped · " if self.cancel.is_set() else ""
            self.app.set_status(f"{lead}{sum(counts.values())} files · {human(sum(sizes.values()))} · {skipped} skipped")
        self.run_bg(lambda: disk_usage(root, self.cancel, remember), done, "Measuring files…")

    def _stats_page(self, page):
        ttk.Button(page, text="Refresh history", command=self.refresh_stats).pack(anchor="w", pady=(0, 8))
        self.stats = Table(page, [("scans", "Analyses", 85, "e"), ("cleans", "Cleans", 85, "e"),
                                  ("freed", "Freed", 120, "e"), ("errors", "Errors", 85, "e")], tree_heading="Date")
        self.stats.pack(fill="both", expand=True)

    def refresh_stats(self):
        self.stats.clear()
        totals = activity_totals(settings.get("autoclean_history", []))
        for day in sorted(totals, reverse=True):
            c = totals[day]
            self.stats.add(text=day, values=(c["scans"], c["cleans"], human(c["freed"]), c["errors"]))
        if not totals:
            self.stats.add(text="No activity recorded yet")
