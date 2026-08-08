import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from web_tool.app import create_app
from web_tool.bilibili_login import BilibiliLogin
from web_tool.config import Settings
from web_tool.secrets import SecretStore


def netscape(*lines: str) -> str:
    return "# Netscape HTTP Cookie File\n" + "\n".join(lines) + "\n"


class BilibiliLoginTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Settings.for_test(Path(self.tmp.name))
        self.login = BilibiliLogin(
            self.settings,
            SecretStore(self.settings.secrets_dir),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_imports_valid_bilibili_cookie_without_exposing_value(self):
        text = netscape(
            ".bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\tsuper-secret",
            ".bilibili.com\tTRUE\t/\tTRUE\t0\tbili_jct\tcsrf-secret",
        )
        result = self.login.import_netscape(text)
        self.assertEqual("logged_in", result["state"])
        self.assertEqual(2, result["cookie_count"])
        self.assertNotIn("super-secret", repr(result))
        self.assertNotIn("csrf-secret", repr(self.login.status()))
        stored = self.settings.secrets_dir / "bilibili-cookies.txt"
        self.assertTrue(stored.is_file())

    def test_rejects_missing_header_malformed_line_and_foreign_domain(self):
        cases = (
            ".bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\tsecret\n",
            netscape(".bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA"),
            netscape(".evil.example\tTRUE\t/\tTRUE\t0\tSESSDATA\tsecret"),
            netscape(".evilbilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\tsecret"),
        )
        for text in cases:
            with self.subTest(text=text), self.assertRaises(ValueError) as raised:
                self.login.import_netscape(text)
            self.assertNotIn("secret", str(raised.exception))

    def test_rejects_cookie_file_without_login_marker(self):
        with self.assertRaises(ValueError):
            self.login.import_netscape(
                netscape(".bilibili.com\tTRUE\t/\tTRUE\t0\tbuvid3\tvalue")
            )

    def test_rejects_files_over_one_mib_without_echoing_content(self):
        marker = "private-cookie-value"
        text = netscape(
            ".bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\t"
            + marker
            + ("x" * (1024 * 1024))
        )
        with self.assertRaises(ValueError) as raised:
            self.login.import_netscape(text)
        self.assertNotIn(marker, str(raised.exception))

    def test_clear_removes_only_managed_login_state(self):
        keep = self.settings.secrets_dir / "provider.keep"
        keep.write_text("keep", encoding="utf-8")
        self.login.import_netscape(
            netscape(".bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\tsecret")
        )
        result = self.login.clear()
        self.assertEqual("logged_out", result["state"])
        self.assertTrue(keep.is_file())
        self.assertFalse(
            (self.settings.secrets_dir / "bilibili-cookies.txt").exists()
        )

    def test_login_api_import_status_qr_and_clear(self):
        app = create_app(self.settings)
        with TestClient(app) as client:
            text = netscape(
                ".bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\tsuper-secret"
            )
            imported = client.post(
                "/api/bilibili/login/cookies",
                json={"text": text},
            )
            self.assertEqual(200, imported.status_code, imported.text)
            self.assertTrue(imported.json()["logged_in"])
            self.assertNotIn("super-secret", repr(imported.json()))
            self.assertNotIn(
                "super-secret",
                repr(client.get("/api/bilibili/login/status").json()),
            )
            self.assertEqual(
                404,
                client.get("/api/bilibili/login/qr").status_code,
            )
            cleared = client.delete("/api/bilibili/login/cookies")
            self.assertEqual("logged_out", cleared.json()["state"])


if __name__ == "__main__":
    unittest.main()
