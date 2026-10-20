"""Self-update and winget-parser robustness tests (no real network: a local HTTP server stands in for GitHub)."""
import hashlib
import http.server
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from woofcleaner import selfupdate, settings, updater


class VersionTests(unittest.TestCase):
    def test_compare(self):
        self.assertTrue(selfupdate.is_newer("0.3.1", "0.3.0"))
        self.assertTrue(selfupdate.is_newer("v0.10.0", "0.9.9"))
        self.assertFalse(selfupdate.is_newer("0.3.0", "0.3.0"))
        self.assertFalse(selfupdate.is_newer("0.2.9", "0.3.0"))


class _Handler(http.server.BaseHTTPRequestHandler):
    files: dict = {}

    def do_GET(self):
        body = self.files.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        self.setup_bytes = b"MZ fake installer"
        good = hashlib.sha256(self.setup_bytes).hexdigest()
        release = {
            "tag_name": "v9.9.9", "body": "Better woofs", "html_url": "https://github.com/o/r/releases/v9.9.9",
            "assets": [
                {"name": "WoofCleaner-Setup-9.9.9.exe", "browser_download_url": f"{self.base}/setup.exe", "size": 17},
                {"name": "WoofCleaner.exe", "browser_download_url": f"{self.base}/portable.exe", "size": 3,
                 "digest": "sha256:" + "0" * 64},
                {"name": "SHA256SUMS.txt", "browser_download_url": f"{self.base}/sums", "size": 10},
            ],
        }
        _Handler.files = {
            "/repos/o/r/releases/latest": json.dumps(release).encode(),
            "/setup.exe": self.setup_bytes,
            "/portable.exe": b"bad",
            "/sums": f"{good}  WoofCleaner-Setup-9.9.9.exe\n".encode(),
        }
        self._td = tempfile.TemporaryDirectory()
        patches = [
            mock.patch.object(selfupdate, "API", self.base + "/repos/{repo}/releases/latest"),
            mock.patch.object(selfupdate, "ALLOWED_HOSTS", (self.base,)),
            mock.patch.object(settings, "SETTINGS", Path(self._td.name) / "settings.json"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._td.cleanup)

    def test_check_finds_newer_release_with_checksums(self):
        rel = selfupdate.check("o/r")
        self.assertEqual(rel.version, "9.9.9")
        self.assertEqual(rel.setup.sha256, hashlib.sha256(self.setup_bytes).hexdigest())  # from SHA256SUMS.txt
        self.assertEqual(rel.portable.sha256, "0" * 64)                                    # from GitHub digest
        self.assertIn("last_check", selfupdate.load_settings())

    def test_download_verifies_hash(self):
        rel = selfupdate.latest_release("o/r")
        f = selfupdate.download(rel.setup)
        self.assertEqual(f.read_bytes(), self.setup_bytes)
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            selfupdate.download(rel.portable)

    def test_refuses_unhashed_or_foreign_downloads(self):
        with self.assertRaisesRegex(RuntimeError, "no SHA-256"):
            selfupdate.download(selfupdate.Asset("x.exe", f"{self.base}/setup.exe", 1, ""))
        with self.assertRaisesRegex(RuntimeError, "unexpected host"):
            selfupdate.download(selfupdate.Asset("x.exe", "http://evil.example/x.exe", 1, "a" * 64))

    def test_up_to_date_returns_none(self):
        with mock.patch.object(selfupdate, "__version__", "9.9.9"):
            self.assertIsNone(selfupdate.check("o/r"))


class LocalisedWingetTests(unittest.TestCase):
    def test_multiword_titles(self):
        text = ("Nama           ID              Versi   Versi Tersedia  Sumber\n"
                "-----------------------------------------------------------\n"
                "Git            Git.Git         2.50.1  2.55.0          winget\n"
                "Foo Bar App    Foo.Bar         1.0     1.2             winget\n")
        ups = updater.parse_table(text)
        self.assertEqual([(u.id, u.version, u.available) for u in ups],
                         [("Git.Git", "2.50.1", "2.55.0"), ("Foo.Bar", "1.0", "1.2")])

    def test_wide_characters_in_names(self):
        # CJK names occupy two terminal cells each; columns must line up by display width.
        text = ("Name        Id            Version Available Source\n"
                "--------------------------------------------------\n"
                "微信        Tencent.WeChat 3.9    4.0       winget\n")
        # "微信" is 2 chars but 4 cells wide, followed by 8 spaces -> Id column at cell 12
        text = text.replace("微信        ", "微信" + " " * 8)
        ups = updater.parse_table(text)
        self.assertEqual(ups[0].id, "Tencent.WeChat")
        self.assertEqual(ups[0].name, "微信")


if __name__ == "__main__":
    unittest.main()
