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
        self.assertIn("function selectFirstProvider", self.javascript)
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

    def test_providers_can_install_local_ollama_on_demand(self):
        self.assertIn('id="provider-install-ollama"', self.html)
        for marker in (
            "function installLocalOllama",
            "http://127.0.0.1:18794/ollama/install",
            "http://ollama:11434",
            "translategemma:4b",
            "Đang cài Ollama và tải model...",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.javascript)

    def test_settings_can_select_and_download_local_whisper(self):
        for marker in (
            'id="settings-asr-engine"',
            'id="settings-whisper-model"',
            'id="settings-whisper-install"',
            'id="settings-qwen-install"',
            'id="settings-qwen-status"',
        ):
            self.assertIn(marker, self.html)
        for marker in (
            "function installLocalWhisper",
            "function installRuntime",
            "http://127.0.0.1:18794/whisper/install",
            "http://127.0.0.1:18794/qwen-asr/install",
            "http://127.0.0.1:18794/install/status",
            "asr_engine",
            "whisper_model",
        ):
                self.assertIn(marker, self.javascript)

    def test_jobs_and_settings_choose_vieneu_by_voice(self):
        for marker in (
            'id="job-asr-engine"',
            'id="job-whisper-model"',
            'id="job-voice"',
            'id="job-vieneu-style"',
            'id="settings-voice"',
            'id="settings-vieneu-style"',
            'id="settings-vieneu-install"',
            'id="settings-vieneu-status"',
            'value="vieneu:hong-chau"',
            'value="story"',
            "Đọc truyện",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)
        for marker in (
            "http://127.0.0.1:18794/vieneu/install",
            "asr_engine",
            "vieneu_style",
            "vieneu:hong-chau",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.javascript)
        self.assertNotIn("tts_engine", self.html)
        self.assertNotIn("tts_engine", self.javascript)

    def test_settings_can_detect_and_apply_hardware_profile(self):
        for marker in (
            'id="settings-hardware-mode"',
            'id="settings-hardware-detect"',
            'id="settings-hardware-status"',
        ):
            self.assertIn(marker, self.html)
        for marker in (
            "function detectHardware",
            "http://127.0.0.1:18794/hardware/apply",
            "hardware_mode",
            "hardware_profile",
        ):
            self.assertIn(marker, self.javascript)

    def test_settings_can_upload_or_download_personal_logo(self):
        for marker in (
            'id="settings-logo-file"',
            'id="settings-logo-url"',
            'id="settings-logo-save"',
            'id="settings-logo-remove"',
            'id="settings-logo-preview"',
        ):
            self.assertIn(marker, self.html)
        for marker in (
            "function saveBrandLogo",
            "function removeBrandLogo",
            "/api/branding/logo-url",
            "/api/branding/logo",
        ):
            self.assertIn(marker, self.javascript)


if __name__ == "__main__":
    unittest.main()
