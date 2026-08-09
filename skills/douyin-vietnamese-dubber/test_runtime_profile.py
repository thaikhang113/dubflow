import json
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


RUN_SH_PATH = Path(__file__).with_name("run.sh")
RUN_SH = RUN_SH_PATH.read_text(encoding="utf-8")


class RuntimeProfileTests(unittest.TestCase):
    def test_free_low_gpu_profile_uses_local_lightweight_defaults(self):
        profile_start = RUN_SH.index('OPENCLAW_RUNTIME_PROFILE="${OPENCLAW_RUNTIME_PROFILE:-standard}"')
        translation_route = RUN_SH.index('source "$SKILL_DIR/translation_route.sh"')
        self.assertLess(profile_start, translation_route)

        expected = (
            'OPENCLAW_AI_PROVIDER="${OPENCLAW_AI_PROVIDER:-ollama}"',
        'OLLAMA_MODEL="${OLLAMA_MODEL:-translategemma:4b}"',
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
        self.assertIn('NINEROUTER_MODEL="${NINEROUTER_MODEL:-}"', RUN_SH)
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


    def test_sync_profile_is_exported_to_quality_gate_processes(self):
        self.assertRegex(RUN_SH, re.compile(r"^export SYNC_MODE TTS_SYNC_POLICY$", re.M))
        self.assertIn(
            'FRAME_STRICT_TOTAL_DRIFT_PER_SEGMENT_MS="${FRAME_STRICT_TOTAL_DRIFT_PER_SEGMENT_MS:-10}"',
            RUN_SH,
        )
        self.assertIn('MAX_FREEZE_PER_SEGMENT_MS="${MAX_FREEZE_PER_SEGMENT_MS:-1500}"', RUN_SH)
        self.assertIn('MAX_FREEZE_PER_SCENE_MS="${MAX_FREEZE_PER_SCENE_MS:-1500}"', RUN_SH)
        self.assertRegex(
            RUN_SH,
            re.compile(r"^export FRAME_STRICT_MAX_SEGMENT_DRIFT_MS FRAME_STRICT_TOTAL_DRIFT_PER_SEGMENT_MS$", re.M),
        )
        self.assertIn(
            "if frame_strict:\n        sync_warning_reasons.append(reason)",
            RUN_SH,
        )
        self.assertIn("tts_resume_cache_is_complete()", RUN_SH)
        self.assertIn(
            'if [[ -n "$RESUME_JOB_DIR" ]] && tts_resume_cache_is_complete',
            RUN_SH,
        )
        self.assertIn('echo "Dùng cached vietnamese_voice.wav/tts_stats.json hợp lệ."', RUN_SH)

    def test_subtitle_band_falls_back_to_cv_without_vision_key(self):
        self.assertIn(
            'if [[ "$SUBTITLE_BAND_DETECT_ENGINE" == "9router_vision" && -z "$OCR_VISION_API_KEY" ]]; then',
            RUN_SH,
        )
        self.assertIn('SUBTITLE_BAND_DETECT_ENGINE="cv"', RUN_SH)
        self.assertNotIn(
            'fail "Thiếu OCR_VISION_API_KEY cho subtitle band 9Router vision."',
            RUN_SH,
        )

    def test_optimizer_status_names_selected_translation_provider(self):
        self.assertNotIn("Đang dịch/tối ưu timing qua 9Router", RUN_SH)
        self.assertIn(
            'Đang dịch/tối ưu timing qua ${OPENCLAW_AI_PROVIDER}',
            RUN_SH,
        )


    def test_asr_provider_auto_routes_and_fingerprints_provider_model_audio(self):
        self.assertIn('ASR_PROVIDER="${ASR_PROVIDER:-auto}"', RUN_SH)
        self.assertIn('QWEN_ASR_ENDPOINT="${QWEN_ASR_ENDPOINT:-http://qwen-asr:8000}"', RUN_SH)
        self.assertIn('ASR_PROVIDER_REPORT_JSON="$OUT_DIR/asr_provider_report.json"', RUN_SH)
        self.assertIn('"provider": provider, "model": model, "audio_sha256": audio_sha256', RUN_SH)
        self.assertIn('if asr_hardware_is_weak; then', RUN_SH)
        self.assertIn('run_qwen_asr "$WHISPER_AUDIO" "$ORIGINAL_SRT"', RUN_SH)
        self.assertIn('run_whisper_asr "$WHISPER_AUDIO" "$ORIGINAL_SRT"', RUN_SH)

    def test_qwen_http_client_posts_audio_and_writes_segments_as_srt(self):
        client = RUN_SH.split("# QWEN_ASR_HTTP_CLIENT_BEGIN\n", 1)[1].split(
            "# QWEN_ASR_HTTP_CLIENT_END", 1
        )[0]
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                body = self.rfile.read(length)
                requests.append((self.path, self.headers["Content-Type"], body))
                payload = json.dumps(
                    {
                        "segments": [
                            {"start": 0.0, "end": 1.25, "text": "Ni hao"},
                            {"start": 1.25, "end": 2.5, "text": "Zai jian"},
                        ]
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                audio = Path(directory) / "audio.wav"
                output = Path(directory) / "original.srt"
                audio.write_bytes(b"RIFFfake-wav")
                result = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        client,
                        str(audio),
                        str(output),
                        f"http://127.0.0.1:{server.server_port}",
                        "qwen3-asr",
                    ],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(
                    (
                        "1\n00:00:00,000 --> 00:00:01,250\nNi hao\n\n"
                        "2\n00:00:01,250 --> 00:00:02,500\nZai jian\n"
                    ),
                    output.read_text(encoding="utf-8"),
                )
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

        self.assertEqual("/v1/transcribe", requests[0][0])
        self.assertIn("multipart/form-data", requests[0][1])
        self.assertIn(b"qwen3-asr", requests[0][2])
        self.assertIn(b"RIFFfake-wav", requests[0][2])

if __name__ == "__main__":
    unittest.main()
