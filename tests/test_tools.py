"""Tests for the toolkit modules. File tests are sandboxed; Windows probes are read-only."""
import os
import tempfile
import time
import unittest
from pathlib import Path

from woofcleaner import duplicates as dup
from woofcleaner import uninstaller as un
from woofcleaner import updater, winutil

WINGET_SAMPLE = """\
   - \r   \\ \r
Name                                 Id                      Version   Available Source
---------------------------------------------------------------------------------------
7-Zip 24.07 (x64)                    7zip.7zip               24.07     26.04     winget
AnyDesk                              AnyDesk.AnyDesk         ad 9.0.12 9.8.2     winget
Some Very Long Application Name Tha\u2026 Vendor.LongApp          1.0       2.0       winget
2 upgrades available.

The following packages have an upgrade available, but require explicit targeting for upgrade:
Name    Id           Version Available Source
-------------------------------------------------
Pinned  Pin.App      1.0     1.1       winget
"""


class DuplicateTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.d = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def w(self, rel, data: bytes, age=0):
        p = self.d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        if age:
            t = time.time() - age
            os.utime(p, (t, t))
        return str(p)

    def test_groups_by_content_not_name_or_size(self):
        big = os.urandom(200_000)
        a = self.w("a/one.bin", big, age=1000)
        b = self.w("b/copy of one.bin", big)
        self.w("c/same-size-different.bin", big[:-1] + bytes([big[-1] ^ 1]))  # same size + same head, differs at end
        self.w("x/small1.txt", b"hello")
        self.w("y/small2.txt", b"hello")
        self.w("z/unique.txt", b"world!")
        groups = dup.find_duplicates([str(self.d)], min_size=1)
        sets = sorted(sorted(os.path.basename(f.path) for f in g.files) for g in groups)
        self.assertEqual(sets, [["copy of one.bin", "one.bin"], ["small1.txt", "small2.txt"]])
        self.assertEqual(groups[0].wasted, 200_000)  # sorted by wasted space
        self.assertEqual(dup.auto_select(groups[:1], "oldest"), [b])
        self.assertEqual(dup.auto_select(groups[:1], "newest"), [a])

    def test_min_size_and_extension_filter(self):
        self.w("1.jpg", b"x" * 50)
        self.w("2.jpg", b"x" * 50)
        self.w("3.png", b"y" * 50)
        self.w("4.png", b"y" * 50)
        self.assertEqual(len(dup.find_duplicates([str(self.d)], min_size=51)), 0)
        g = dup.find_duplicates([str(self.d)], extensions={".png"})
        self.assertEqual(len(g), 1)

    def test_never_lose_every_copy(self):
        self.w("p.bin", b"z" * 10)
        self.w("q.bin", b"z" * 10)
        groups = dup.find_duplicates([str(self.d)])
        everything = {f.path for g in groups for f in g.files}
        self.assertEqual(len(dup.check_selection(groups, everything)), 1)
        self.assertEqual(dup.check_selection(groups, set(dup.auto_select(groups))), [])


class ParsingTests(unittest.TestCase):
    def test_winget_table(self):
        ups = updater.parse_table(WINGET_SAMPLE)
        self.assertEqual([u.id for u in ups], ["7zip.7zip", "AnyDesk.AnyDesk", "Vendor.LongApp", "Pin.App"])
        self.assertEqual(ups[0].available, "26.04")
        self.assertEqual(ups[1].version, "ad 9.0.12")
        self.assertEqual(ups[2].name, "Some Very Long Application Name Tha")

    def test_split_command_line(self):
        self.assertEqual(winutil.split_command_line('"C:\\Program Files\\A\\unins000.exe" /SILENT'),
                         ("C:\\Program Files\\A\\unins000.exe", "/SILENT"))
        self.assertEqual(winutil.split_command_line("C:\\Program Files\\B App\\uninst.exe -x"),
                         ("C:\\Program Files\\B App\\uninst.exe", "-x"))
        self.assertEqual(winutil.split_command_line("MsiExec.exe /I{1234}"), ("MsiExec.exe", "/I{1234}"))

    def test_msi_repair_string_becomes_uninstall(self):
        p = un.Program(name="X", uninstall_string="MsiExec.exe /I{AAAA-BBBB}")
        self.assertEqual(un.uninstall_command(p), ("MsiExec.exe", "/x {AAAA-BBBB}"))
        p = un.Program(name="Y", product_code="{C0FFEE}")
        self.assertEqual(un.uninstall_command(p, quiet=True), ("msiexec.exe", "/x {C0FFEE} /qb"))

    def test_base_name(self):
        self.assertEqual(un.base_name("7-Zip 24.07 (x64)"), "7-Zip")
        self.assertEqual(un.base_name("CPUID HWMonitor 1.46"), "CPUID HWMonitor")
        self.assertEqual(un.base_name("Docker Desktop"), "Docker Desktop")


@unittest.skipUnless(winutil.IS_WINDOWS, "Windows only")
class ReadOnlyWindowsProbes(unittest.TestCase):
    def test_programs_listed(self):
        progs = un.list_programs()
        self.assertGreater(len(progs), 0)
        self.assertTrue(all(p.name for p in progs))

    def test_startup_listing(self):
        from woofcleaner import startup
        items = startup.list_items(include_tasks=False)
        self.assertTrue(all(i.kind in ("registry", "folder") for i in items))


if __name__ == "__main__":
    unittest.main()
