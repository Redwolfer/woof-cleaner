"""End-to-end checks on disposable folders and isolated user settings."""
import csv
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from woofcleaner import cli, reports, scheduler, settings, winutil
from woofcleaner.engine import Context, Mode, RuleResult, run
from woofcleaner.rules import Action, Rule, RuleSet, load_rules


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        p = patch.object(settings, "SETTINGS", self.root / "settings.json")
        p.start()
        self.addCleanup(p.stop)
        self.ini = self.root / "rules.ini"
        self.ini.write_text("[Unused]\nID=unused\n")

    def test_folder_rules_manual_and_scheduled(self):
        target = self.root / "cache"
        protected = target / "keep"
        protected.mkdir(parents=True)
        kept = protected / "original"
        kept.write_bytes(b"keep")
        (protected / "empty").mkdir()
        disposable = target / "junk"
        disposable.write_bytes(b"remove")
        settings.save(included_folders=[str(target)], excluded_folders=[str(protected)],
                      clean_selection=["user.folders"])
        rs = load_rules(self.ini)
        preview = run(["user.folders"], Context(rs))[0]
        self.assertEqual((preview.files, preview.bytes), (1, 6))
        self.assertTrue(disposable.exists())
        for method in ("clean", "auto-clean"):
            disposable.write_bytes(b"remove")
            args = ["--rules-file", str(self.ini), method]
            if method == "clean":
                args += ["--rules", "user.folders", "--yes"]
            self.assertEqual(cli.main(args), 0)
            self.assertFalse(disposable.exists())
            self.assertEqual(kept.read_bytes(), b"keep")
            self.assertTrue((protected / "empty").is_dir())

    @unittest.skipUnless(winutil.IS_WINDOWS, "Windows junction")
    def test_custom_folder_through_junction_is_skipped(self):
        outside = self.root / "protected"
        inside = outside / "inside"
        inside.mkdir(parents=True)
        file = inside / "keep"
        file.write_text("keep")
        link = self.root / "junction"
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True)
        self.addCleanup(os.rmdir, link)
        skipped_paths = []
        _, _, skipped = reports.disk_usage(self.root, threading.Event(), lambda p, _: skipped_paths.append(p))
        self.assertEqual(skipped, 1)
        self.assertEqual(skipped_paths, [str(link)])
        settings.save(included_folders=[str(link / "inside")])
        rs = load_rules(self.ini)
        self.assertEqual(run(["user.folders"], Context(rs, mode=Mode.CLEAN))[0].files, 0)
        self.assertTrue(file.exists())

    def test_activity_keeps_legacy_and_separates_estimates(self):
        settings.save(autoclean_history=[{"time":"2026-10-01 08:00","freed":20,"trigger":"logon"}])
        result = RuleResult("t", "test", Mode.ANALYSE, bytes=600)
        scheduler.record_results([result], Mode.ANALYSE, "CLI")
        result.errors.append("locked")
        scheduler.record_results([result], Mode.CLEAN, "Custom Clean")
        scheduler.record_results([], Mode.CLEAN, "Custom Clean", cancelled=True)
        rows = settings.get("autoclean_history")
        self.assertEqual([r["status"] for r in rows[1:]], ["Completed","Partial","Cancelled"])
        totals = reports.activity_totals(rows)
        self.assertEqual(sum(r["freed"] for r in totals.values()), 620)
        self.assertEqual(sum(r["scans"] for r in totals.values()), 1)

    def test_failed_windows_actions_do_not_inflate_clean_history(self):
        rule = Rule(name="Fixture", id="fixture", actions=[Action("EmptyRecycleBin"), Action("CleanWindowsEventLogs")])
        rules = RuleSet(rules=[rule])
        before = [("A", 5, 70), ("B", 3, 60)]
        after = [("A", 0, 20), ("B", 3, 60)]
        with (patch.object(winutil, "IS_WINDOWS", True),
              patch.object(winutil, "recycle_bin_info", return_value=(100, 2)),
              patch.object(winutil, "empty_recycle_bin", side_effect=OSError("locked")),
              patch.object(winutil, "event_logs", side_effect=[before, after]),
              patch.object(winutil, "clear_event_logs", return_value=["B"])):
            result, = run(["fixture"], Context(rules, mode=Mode.CLEAN))
        self.assertEqual((result.files, result.records, result.bytes), (0, 5, 50))
        self.assertEqual(len(result.errors), 2)

    def test_duplicate_partial_move_then_retry(self):
        from woofcleaner import duplicates
        paths = [self.root / name for name in ("keeper", "moved", "retry")]
        for file in paths:
            file.write_text("same")
        groups = duplicates.find_duplicates([str(self.root)])
        selected = {str(p) for p in paths[1:]}
        def move(files):
            if files[0] == str(paths[-1]):
                raise OSError("locked")
            Path(files[0]).unlink()
        with patch.object(winutil, "send_to_recycle_bin", side_effect=move):
            results = duplicates.recycle_selected(groups, selected)
        self.assertEqual(results[str(paths[1])], duplicates.MOVED)
        self.assertIn("locked", results[str(paths[-1])])
        with patch.object(winutil, "send_to_recycle_bin", side_effect=lambda items: Path(items[0]).unlink()):
            results.update(duplicates.recycle_selected(groups, {str(paths[-1])}))
        self.assertEqual(set(results.values()), {duplicates.MOVED})
        self.assertTrue(paths[0].exists())

    def test_csv_and_disk_totals(self):
        folder = self.root / "files"
        folder.mkdir()
        file = folder / "hasil,é.txt"
        file.write_bytes(b"123")
        (folder / "two.txt").write_bytes(b"4567")
        (folder / "data.bin").write_bytes(b"89")
        sizes, counts, skipped = reports.disk_usage(folder, threading.Event())
        self.assertEqual((sizes[".txt"],counts[".txt"],sum(sizes.values()),skipped),(7,2,9,0))
        result = RuleResult("sample", "Sample", Mode.ANALYSE, items=[(str(file),3)])
        path = self.root / "report.csv"
        reports.write_csv(path, reports.clean_rows([result]))
        with path.open(encoding="utf-8-sig",newline="") as stream:
            rows = list(csv.reader(stream))
        self.assertEqual(rows[2][3],str(file))
        self.assertEqual(len(list(reports.clean_rows([]))),1)
