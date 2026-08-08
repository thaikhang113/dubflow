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
            'id="bilibili-cookie-form"',
            'id="channel-form"',
            'id="channel-list"',
            'id="series-list"',
            'id="trend-form"',
            'id="settings-form"',
            'id="settings-thumbnail"',
            'id="settings-export"',
            'id="queue-pause"',
            'id="job-list"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)
        self.assertIn('new EventSource("/api/events")', self.javascript)

    def test_untrusted_content_never_uses_html_injection(self):
        self.assertNotIn("innerHTML", self.javascript)
        self.assertNotIn("insertAdjacentHTML", self.javascript)
        self.assertNotIn("localStorage", self.javascript)
        self.assertNotIn("hero", self.html.lower())


if __name__ == "__main__":
    unittest.main()
