"""Tests for the 0.4 features: browser databases, registry cleaner, schedules, skip/ignore, allowlist.

Browser databases are built in a temp folder. Registry tests only touch HKCU\\Software\\WoofCleanerTest,
which they create and delete. Nothing else on the system is changed.
"""
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from woofcleaner import browserdb, drivers, regscan, scheduler, settings, updater, winutil
from woofcleaner.engine import Context, Mode, run
from woofcleaner.rules import parse_rules


def make_db(path: Path, script: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(script)
    con.commit()
    con.close()


def rows(path: Path, sql: str):
    con = sqlite3.connect(path)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


CHROME_HISTORY = """
CREATE TABLE meta(key TEXT, value TEXT); INSERT INTO meta VALUES('version','70');
CREATE TABLE urls(id INTEGER PRIMARY KEY, url TEXT); INSERT INTO urls(url) VALUES('https://a'),('https://b'),('https://c');
CREATE TABLE visits(id INTEGER PRIMARY KEY, url INTEGER); INSERT INTO visits(url) VALUES(1),(2),(2),(3);
CREATE TABLE keyword_search_terms(term TEXT); INSERT INTO keyword_search_terms VALUES('cats');
CREATE TABLE downloads(id INTEGER PRIMARY KEY, target_path TEXT); INSERT INTO downloads(target_path) VALUES('C:\\x.zip');
CREATE TABLE downloads_url_chains(id INTEGER, url TEXT); INSERT INTO downloads_url_chains VALUES(1,'https://dl');
"""
CHROME_COOKIES = """
CREATE TABLE cookies(host_key TEXT, name TEXT);
INSERT INTO cookies VALUES('.google.com','SID'),('mail.google.com','x'),('.tracker.net','id'),('ads.example.org','y');
"""
FIREFOX_PLACES = """
CREATE TABLE moz_places(id INTEGER PRIMARY KEY, url TEXT, visit_count INTEGER, last_visit_date INTEGER, origin_id INTEGER);
CREATE TABLE moz_historyvisits(id INTEGER PRIMARY KEY, place_id INTEGER);
CREATE TABLE moz_bookmarks(id INTEGER PRIMARY KEY, fk INTEGER, title TEXT);
CREATE TABLE moz_inputhistory(place_id INTEGER, input TEXT);
CREATE TABLE moz_annos(id INTEGER PRIMARY KEY, place_id INTEGER, content TEXT);
CREATE TABLE moz_origins(id INTEGER PRIMARY KEY, host TEXT);
INSERT INTO moz_origins VALUES(1,'bookmarked.org'),(2,'visited.com');
INSERT INTO moz_places VALUES(1,'https://bookmarked.org',5,111,1),(2,'https://visited.com/a',3,222,2),(3,'https://visited.com/b',1,333,2);
INSERT INTO moz_historyvisits(place_id) VALUES(1),(1),(2),(3),(3);
INSERT INTO moz_bookmarks VALUES(1,1,'Keep me'),(2,NULL,'a folder');
INSERT INTO moz_inputhistory VALUES(2,'vis');
INSERT INTO moz_annos VALUES(1,2,'download'),(2,1,'bookmark note');
"""


class BrowserDbTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.chrome = self.root / "Local" / "Chrome" / "User Data" / "Default"
        make_db(self.chrome / "History", CHROME_HISTORY)
        make_db(self.chrome / "Network" / "Cookies", CHROME_COOKIES)
        self.ff = self.root / "Roaming" / "Firefox" / "Profiles" / "abc.default"
        make_db(self.ff / "places.sqlite", FIREFOX_PLACES)

    def tearDown(self):
        self._td.cleanup()

    def test_chromium_history_analyse_then_clean(self):
        r = browserdb.process("chromiumhistory", str(self.chrome), False, [])
        self.assertEqual(r.records, 3)                                   # urls
        self.assertEqual(rows(self.chrome / "History", "SELECT COUNT(*) FROM visits")[0][0], 4)  # analyse = no change
        r = browserdb.process("chromiumhistory", str(self.chrome), True, [])
        self.assertEqual(r.records, 3)
        db = self.chrome / "History"
        self.assertEqual(rows(db, "SELECT COUNT(*) FROM urls")[0][0], 0)
        self.assertEqual(rows(db, "SELECT COUNT(*) FROM visits")[0][0], 0)
        self.assertEqual(rows(db, "SELECT COUNT(*) FROM keyword_search_terms")[0][0], 0)
        self.assertEqual(rows(db, "SELECT COUNT(*) FROM downloads")[0][0], 1, "downloads are a separate rule")
        self.assertEqual(rows(db, "SELECT value FROM meta")[0][0], "70", "meta must survive")

    def test_chromium_downloads(self):
        r = browserdb.process("chromiumdownloads", str(self.chrome), True, [])
        self.assertEqual(r.records, 1)
        db = self.chrome / "History"
        self.assertEqual(rows(db, "SELECT COUNT(*) FROM downloads_url_chains")[0][0], 0)
        self.assertEqual(rows(db, "SELECT COUNT(*) FROM urls")[0][0], 3)

    def test_cookie_allowlist(self):
        allow = ["google.com"]
        self.assertEqual(browserdb.process("chromiumcookies", str(self.chrome), False, allow).records, 2)
        browserdb.process("chromiumcookies", str(self.chrome), True, allow)
        left = sorted(h for (h,) in rows(self.chrome / "Network" / "Cookies", "SELECT host_key FROM cookies"))
        self.assertEqual(left, [".google.com", "mail.google.com"])

    def test_firefox_history_keeps_bookmarks(self):
        db = self.ff / "places.sqlite"
        self.assertEqual(browserdb.process("firefoxhistory", str(self.ff), False, []).records, 5)
        browserdb.process("firefoxhistory", str(self.ff), True, [])
        self.assertEqual(rows(db, "SELECT COUNT(*) FROM moz_historyvisits")[0][0], 0)
        self.assertEqual(rows(db, "SELECT id, visit_count, last_visit_date FROM moz_places"), [(1, 0, None)])
        self.assertEqual(rows(db, "SELECT COUNT(*) FROM moz_bookmarks")[0][0], 2)
        self.assertEqual(rows(db, "SELECT place_id FROM moz_annos"), [(1,)])
        self.assertEqual(rows(db, "SELECT host FROM moz_origins"), [("bookmarked.org",)])

    def test_locked_database_is_reported_not_raised(self):
        con = sqlite3.connect(self.chrome / "History", isolation_level=None)
        con.execute("BEGIN EXCLUSIVE")
        try:
            r = browserdb.process("chromiumhistory", str(self.chrome), True, [], label="Chrome")
        finally:
            con.execute("ROLLBACK")
            con.close()
        self.assertTrue(any("close it" in n for n in r.notes), r.notes)
        self.assertEqual(rows(self.chrome / "History", "SELECT COUNT(*) FROM urls")[0][0], 3)

    def test_engine_rule_uses_actions_and_allowlist(self):
        ini = r"""
[Rule Vars]
CHROME_PROFILES=%LOCALAPPDATA%\Chrome\User Data\Default
[Chrome Cookies]
ID=c.cookies
Action1=ChromiumCookies|<CHROME_PROFILES>
[Chrome History]
ID=c.history
Action1=ChromiumHistory|<CHROME_PROFILES>
"""
        rs = parse_rules(ini)
        env = {"LOCALAPPDATA": str(self.root / "Local")}
        res = {r.rule_id: r for r in run(["c.cookies", "c.history"],
                                         Context(rs, env=env, running=set(), cookie_allowlist=["tracker.net"]))}
        self.assertEqual(res["c.cookies"].records, 3)
        self.assertEqual(res["c.history"].records, 3)
        self.assertTrue(res["c.history"].found_anything)
        run(["c.cookies"], Context(rs, env=env, running=set(), mode=Mode.CLEAN, cookie_allowlist=["tracker.net"]))
        left = [h for (h,) in rows(self.chrome / "Network" / "Cookies", "SELECT host_key FROM cookies")]
        self.assertEqual(left, [".tracker.net"])


class AllowlistTests(unittest.TestCase):
    def test_domains(self):
        self.assertEqual(settings.normalise_domain(" https://www.Example.com/login?x=1 "), "example.com")
        self.assertTrue(settings.domain_allowed(".mail.google.com", ["google.com"]))
        self.assertTrue(settings.domain_allowed("google.com", ["google.com"]))
        self.assertFalse(settings.domain_allowed("notgoogle.com", ["google.com"]))
        self.assertFalse(settings.domain_allowed("google.com.evil.net", ["google.com"]))


class SettingsSandbox(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self._p = mock.patch.object(settings, "SETTINGS", Path(self._td.name) / "settings.json")
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self._td.cleanup()


class SkipIgnoreTests(SettingsSandbox):
    def test_software(self):
        ups = [updater.Upgrade("Git", "Git.Git", "2.50", "2.55"), updater.Upgrade("7-Zip", "7zip.7zip", "24", "26"),
               updater.Upgrade("Zoom", "Zoom.Zoom", "5", "6")]
        updater.skip_version("Git.Git", "2.55")
        updater.ignore("Zoom.Zoom")
        active, skipped, ignored = updater.classify(ups)
        self.assertEqual([u.id for u in active], ["7zip.7zip"])
        self.assertEqual([u.id for u in skipped], ["Git.Git"])
        self.assertEqual([u.id for u in ignored], ["Zoom.Zoom"])
        # a newer version than the skipped one shows up again
        ups[0].available = "2.56"
        self.assertIn(ups[0], updater.classify(ups)[0])
        updater.resume("Zoom.Zoom")
        self.assertEqual(updater.classify(ups)[2], [])

    def test_drivers(self):
        a = drivers.DriverUpdate("Intel - System - 1.0", "id-1", "System", "Intel", "Chipset", "2024-01-01", 1.0)
        b = drivers.DriverUpdate("Realtek - Audio - 6.0", "id-2", "Audio", "Realtek", "HD Audio", "2024-01-01", 2.0)
        drivers.skip_update(a)
        drivers.ignore_device(b)
        newer_b = drivers.DriverUpdate("Realtek - Audio - 6.1", "id-3", "Audio", "Realtek", "HD Audio", "2025-01-01", 2)
        active, skipped, ignored = drivers.classify([a, b, newer_b])
        self.assertEqual((active, skipped, [u.update_id for u in ignored]), ([], [a], ["id-2", "id-3"]))
        drivers.resume(a)
        self.assertEqual(drivers.classify([a])[0], [a])


class SchedulerTests(SettingsSandbox):
    def test_calendar_triggers(self):
        now = datetime(2026, 10, 20, 12, 0)    # a Tuesday
        s = scheduler.Schedule("x", "biweekly", "Friday", "09:30")
        xml = scheduler.calendar_trigger(s, now)
        self.assertIn("<StartBoundary>2026-10-23T09:30:00</StartBoundary>", xml)
        self.assertIn("<Friday />", xml)
        self.assertIn("<WeeksInterval>2</WeeksInterval>", xml)
        xml = scheduler.calendar_trigger(scheduler.Schedule("y", "daily", time="23:45"), now)
        self.assertIn("2026-10-20T23:45:00", xml)
        self.assertIn("<DaysInterval>1</DaysInterval>", xml)

    def test_task_xml(self):
        exe, args, cwd = scheduler.launch_command("auto-clean", "--trigger", "abc")
        self.assertTrue(exe.lower().endswith(("pythonw.exe", "python.exe", "woofcleaner.exe")))
        self.assertIn("auto-clean --trigger abc", args)
        xml = scheduler.task_xml("<X/>", exe, args, cwd, True, "a & b")
        self.assertIn("<StartWhenAvailable>true</StartWhenAvailable>", xml)
        self.assertIn("<RunLevel>HighestAvailable</RunLevel>", xml)
        self.assertIn("a &amp; b", xml)

    def test_validation_and_history(self):
        with self.assertRaises(ValueError):
            scheduler.add_schedule("hourly")
        with self.assertRaises(ValueError):
            scheduler.add_schedule("weekly", time="25:00")
        scheduler.record_run("x", 1024, 3, 7, 2, 0)
        self.assertEqual(settings.get("autoclean_history")[0]["records"], 7)


@unittest.skipUnless(winutil.IS_WINDOWS, "Windows registry")
class RegistryCleanerTests(unittest.TestCase):
    KEY = r"HKCU\Software\WoofCleanerTest"

    def setUp(self):
        import winreg
        self.winreg = winreg
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.gone = str(self.tmp / "deleted" / "app.exe")
        self.here = self.tmp / "present.exe"
        self.here.write_bytes(b"MZ")
        winutil.reg_set(self.KEY + r"\Run", "Ghost", 1, f'"{self.gone}" --tray')
        winutil.reg_set(self.KEY + r"\Run", "Alive", 1, f'"{self.here}"')
        winutil.reg_set(self.KEY + r"\App Paths\ghost.exe", None, 1, self.gone)
        winutil.reg_set(self.KEY + r"\App Paths\ghost.exe", "Path", 1, str(self.tmp))

    def tearDown(self):
        if winutil.reg_key_exists(self.KEY):
            winutil.reg_delete_tree_view(self.KEY)
        self._td.cleanup()

    def test_is_missing_is_conservative(self):
        self.assertTrue(regscan.is_missing(self.gone))
        self.assertFalse(regscan.is_missing(str(self.here)))
        self.assertFalse(regscan.is_missing(r"relative\path.exe"))
        self.assertFalse(regscan.is_missing(r"\\server\share\x.exe"))
        self.assertFalse(regscan.is_missing(r"C:\Program Files\WindowsApps\X\x.exe"))
        self.assertEqual(regscan.exe_of(f'"{self.gone}" /x'), self.gone)
        self.assertIsNone(regscan.exe_of(r"C:\Windows\System32\rundll32.exe shell32.dll,Foo"))
        self.assertIsNone(regscan.exe_of("notepad.exe"))

    def test_fix_and_restore_roundtrip(self):
        issues = [regscan.Issue("startup", "ghost", self.KEY + r"\Run", "Ghost", "delete_value"),
                  regscan.Issue("apppaths", "ghost", self.KEY + r"\App Paths\ghost.exe", None, "delete_key")]
        fixed, errors, backup = regscan.fix(issues, self.tmp / "backups")
        self.assertEqual((fixed, errors), (2, []))
        self.assertFalse(winutil.reg_value_exists(self.KEY + r"\Run", "Ghost"))
        self.assertTrue(winutil.reg_value_exists(self.KEY + r"\Run", "Alive"))
        self.assertFalse(winutil.reg_key_exists(self.KEY + r"\App Paths\ghost.exe"))
        data = json.loads(backup.read_text(encoding="utf-8"))
        self.assertEqual(data["format"], "woof-registry-v2")
        n, errors = regscan.restore(backup)
        self.assertEqual((n, errors), (2, []))
        self.assertEqual(winutil.reg_get(self.KEY + r"\Run", "Ghost"), f'"{self.gone}" --tray')
        self.assertEqual(winutil.reg_get(self.KEY + r"\App Paths\ghost.exe", "Path"), str(self.tmp))

    def test_real_scan_only_reads(self):
        issues = regscan.scan(["muicache", "startup"])
        self.assertTrue(all(isinstance(i, regscan.Issue) for i in issues))


if __name__ == "__main__":
    unittest.main()
