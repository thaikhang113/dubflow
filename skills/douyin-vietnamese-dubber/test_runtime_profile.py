import re
import unittest
from pathlib import Path


RUN_SH = Path(__file__).with_name("run.sh").read_text(encoding="utf-8")


class RuntimeProfileTests(unittest.TestCase):
    def test_free_low_gpu_profile_uses_local_lightweight_defaults(self):
        profile_start = RUN_SH.index('OPENCLAW_RUNTIME_PROFILE="${OPENCLAW_RUNTIME_PROFILE:-standard}"')
        translation_route = RUN_SH.index('source "$SKILL_DIR/translation_route.sh"')
        self.assertLess(profile_start, translation_route)

        expected = (
            'OPENCLAW_AI_PROVIDER="${OPENCLAW_AI_PROVIDER:-ollama}"',
            'OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:3b}"',
            'EDGE_TTS_VOICE="${EDGE_TTS_VOICE:-vi-VN-HoaiMyNeural}"',
            'SUBTITLE_OCR_ENGINE="${SUBTITLE_OCR_ENGINE:-paddleocr}"',
            'SUBTITLE_BAND_DETECT_ENGINE="${SUBTITLE_BAND_DETECT_ENGINE:-cv}"',
            'BGM_MODE="${BGM_MODE:-none}"',
            'SPEECH_ONLY_PREPROCESS="${SPEECH_ONLY_PREPROCESS:-0}"',
            'AI33_TTS_WORKERS="${AI33_TTS_WORKERS:-1}"',
            'TTS_VOICE_QA_ENABLED="${TTS_VOICE_QA_ENABLED:-0}"',
        )
        for setting in expected:
            with self.subTest(setting=setting):
                self.assertIn(setting, RUN_SH)
        self.assertRegex(RUN_SH, re.compile(r"^export OPENCLAW_AI_PROVIDER$", re.M))
        self.assertIn(
            'if [[ -z "${OPENCLAW_DEFAULT_TTS_VOICE:-}" && -f "$VOICE_REGISTRY_PY" ]]; then',
            RUN_SH,
        )

    def test_credentials_are_not_required_unconditionally(self):
        forbidden = (
            "RESONA_API_TOKEN:?",
            "AI33_API_KEY:?",
            "API_KEY:?",
            "OCR_VISION_API_KEY:?",
            "DOUYIN_DUBBER_API_KEY:?",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, RUN_SH)

    def test_selected_provider_dependencies_are_checked(self):
        self.assertRegex(
            RUN_SH,
            re.compile(
                r'if \[\[ "\$voice_lower" == ai33:\* \]\]; then.*?'
                r'\[\[ -n "\$AI33_API_KEY" \]\].*?'
                r'elif \[\[ "\$voice_lower" == resona:\* \]\]; then.*?'
                r'\[\[ -n "\$RESONA_API_TOKEN" \]\].*?'
                r'elif \[\[ "\$voice_lower" == kokoro:\* \]\]; then.*?'
                r'else\s+need_cmd edge-tts',
                re.S,
            ),
        )
        self.assertIn('API_KEY="$(get_api_key)"', RUN_SH)
        self.assertIn(
            '[[ "$OPENCLAW_AI_PROVIDER" == "ollama" ]] || [[ -n "$API_KEY" ]]',
            RUN_SH,
        )


if __name__ == "__main__":
    unittest.main()
