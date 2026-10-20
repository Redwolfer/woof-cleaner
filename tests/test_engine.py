"""Sandboxed tests: every path lives in a temp dir; nothing on the real system is touched."""
import os
import tempfile
import time
import unittest
from pathlib import Path

from woofcleaner.engine import Context, Mode, expand_env, expand_variants, glob_paths, run, run_rule
from woofcleaner.rules import parse_rules

INI = r"""
[Rule Vars]
PROFILES=%LOCALAPPDATA%\Browser\Default,%LOCALAPPDATA%\Browser\Profile*

[Temp (old only)]
ID=t.old
OnFile1=*|FileDeleteIfOlderThan|24hours
FileKey1=%TEMP%|*|RECURSE

[Cache]
ID=t.cache
DetectFile1=<PROFILES>
FileKey1=<PROFILES>\Cache|*.*|RECURSE|REMOVESELF
ExcludeKey1=FILE|%LOCALAPPDATA%\Browser\Default\Cache\keep.me

[Shallow]
ID=t.flat
FileKey1=%LOCALAPPDATA%\Flat|*.tmp;*.old

[Danger]
ID=t.danger
FileKey1=%SYSTEMDRIVE%\|*|RECURSE

[Missing App]
ID=t.missing
DetectFile1=%LOCALAPPDATA%\NoSuchApp
FileKey1=%LOCALAPPDATA%\NoSuchApp|*|RECURSE
"""


def touch(path: Path, size=10, age_hours=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    if age_hours:
        t = time.time() - age_hours * 3600
        os.utime(path, (t, t))


class EngineTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name) / "u" / "AppData" / "Local"
        self.root.mkdir(parents=True)
        self.env = {"LOCALAPPDATA": str(self.root), "TEMP": str(self.root / "Temp"),
                    "SYSTEMDRIVE": os.path.splitdrive(self._td.name)[0] or "C:"}
        self.rs = parse_rules(INI)

    def tearDown(self):
        self._td.cleanup()

    def ctx(self, mode):
        return Context(self.rs, env=self.env, mode=mode, running=set(), os_version=(10, 0))

    def test_parse(self):
        r = self.rs.by_id()["t.cache"]
        fk = r.file_keys[0]
        self.assertTrue(fk.recurse and fk.remove_self)
        self.assertEqual(r.excludes[0].kind, "FILE")
        self.assertEqual(self.rs.vars["PROFILES"][0].split("\\")[-1], "Default")

    def test_env_and_variants(self):
        self.assertIsNone(expand_env(r"%NOPE%\x", self.env))
        self.assertEqual(len(expand_variants(r"<PROFILES>\Cache", self.rs.vars)), 2)

    def test_glob(self):
        touch(self.root / "Browser" / "Profile 1" / "a.txt")
        touch(self.root / "Browser" / "Profile 2" / "a.txt")
        self.assertEqual(len(glob_paths(str(self.root / "Browser" / "Profile*"))), 2)

    def test_analyse_never_deletes(self):
        f = self.root / "Temp" / "old.bin"
        touch(f, 100, age_hours=48)
        res = run_rule(self.rs.by_id()["t.old"], self.ctx(Mode.ANALYSE))
        self.assertEqual((res.files, res.bytes), (1, 100))
        self.assertTrue(f.exists())

    def test_age_filter_and_clean(self):
        old, new = self.root / "Temp" / "old.bin", self.root / "Temp" / "sub" / "new.bin"
        touch(old, 100, age_hours=48)
        touch(new, 50, age_hours=1)
        res = run_rule(self.rs.by_id()["t.old"], self.ctx(Mode.CLEAN))
        self.assertEqual(res.files, 1)
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())

    def test_recurse_removeself_and_exclude(self):
        base = self.root / "Browser" / "Default" / "Cache"
        touch(base / "a" / "1.bin")
        touch(base / "2.bin")
        touch(base / "keep.me")
        other = self.root / "Browser" / "Profile 3" / "Cache" / "x" / "3.bin"
        touch(other)
        res = run_rule(self.rs.by_id()["t.cache"], self.ctx(Mode.CLEAN))
        self.assertEqual(res.files, 3)
        self.assertTrue((base / "keep.me").exists())     # excluded file survives
        self.assertTrue(base.exists())                   # so the dir is not removed
        self.assertFalse(other.parent.parent.exists())   # fully emptied -> REMOVESELF

    def test_nonrecursive_patterns(self):
        flat = self.root / "Flat"
        touch(flat / "a.tmp")
        touch(flat / "b.old")
        touch(flat / "c.keep")
        touch(flat / "deep" / "d.tmp")
        res = run_rule(self.rs.by_id()["t.flat"], self.ctx(Mode.CLEAN))
        self.assertEqual(res.files, 2)
        self.assertTrue((flat / "c.keep").exists() and (flat / "deep" / "d.tmp").exists())

    def test_not_installed_is_skipped(self):
        res = run_rule(self.rs.by_id()["t.missing"], self.ctx(Mode.CLEAN))
        self.assertFalse(res.applicable)

    def test_refuses_drive_root(self):
        res = run_rule(self.rs.by_id()["t.danger"], self.ctx(Mode.ANALYSE))
        self.assertEqual(res.files, 0)
        self.assertTrue(any("refused" in e for e in res.errors))

    @unittest.skipUnless(os.name == "nt", "junctions are Windows-only")
    def test_does_not_follow_junctions(self):
        import subprocess
        outside = Path(self._td.name) / "outside"
        touch(outside / "precious.txt")
        link = self.root / "Flat" / "link"
        (self.root / "Flat").mkdir(parents=True)
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
        if r.returncode != 0:
            self.skipTest("could not create junction")
        self.rs = parse_rules("[L]\nID=t.l\nFileKey1=%LOCALAPPDATA%\\Flat|*|RECURSE\n")
        run(["t.l"], self.ctx(Mode.CLEAN))
        self.assertTrue((outside / "precious.txt").exists())


if __name__ == "__main__":
    unittest.main()
