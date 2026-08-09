import unittest
from pathlib import Path


class StaticUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        static = Path(__file__).resolve().parents[1] / "static"
        cls.html = (static / "index.html").read_text(encoding="utf-8")
        cls.javascript = (static / "app.js").read_text(encoding="utf-8")

    def test_jobs_and_providers_contract(self):
        for marker in (
            'data-view="jobs"',
            'data-view="providers"',
            'data-view="bilibili-login"',
            'data-view="channels"',
            'data-view="series"',
            'data-view="trend"',
            'data-view="settings"',
            'id="new-job-form"',
            'id="provider-form"',
            'id="bilibili-login-start"',
            'id="bilibili-host-open"',
            'id="bilibili-cookie-form"',
            'id="channel-form"',
            'id="channel-list"',
            'id="series-list"',
            'id="trend-form"',
            'id="settings-form"',
            'id="settings-doctor-result"',
            'id="settings-thumbnail"',
            'id="settings-export"',
            'id="queue-pause"',
            'id="job-list"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)
        self.assertIn('new EventSource("/api/events")', self.javascript)
        self.assertIn("http://127.0.0.1:18794/open", self.javascript)
        self.assertIn("function renderDoctor", self.javascript)
        self.assertIn('if (name === "settings")', self.javascript)
        self.assertIn("loadDoctor()", self.javascript)

    def test_untrusted_content_never_uses_html_injection(self):
        self.assertNotIn("innerHTML", self.javascript)
        self.assertNotIn("insertAdjacentHTML", self.javascript)
        self.assertNotIn("localStorage", self.javascript)
        self.assertNotIn("hero", self.html.lower())

    def test_doctor_is_actionable_for_nontechnical_users(self):
        for marker in (
            "function doctorAdvice",
            "function doctorAction",
            "Đang dùng được",
            "Cần thiết lập",
            "Không bắt buộc",
            "Mở phần thiết lập",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.javascript)
        self.assertLess(
            self.html.index('id="settings-doctor-result"'),
            self.html.index('id="settings-form"'),
        )
        self.assertIn("Đang kiểm tra cấu hình...", self.javascript)


if __name__ == "__main__":
    unittest.main()
