#!/usr/bin/env python3
import json
import subprocess
import sys
import tempfile
import threading
import unittest
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RUN_SH = Path(__file__).with_name("run.sh")
SPEECH_PREPROCESS = Path(__file__).with_name("speech_only_preprocess.py")


class TTSWorkerTests(unittest.TestCase):
    def test_ai33_prefetch_uses_three_worker_cap_and_keeps_ordered_results(self):
        source = RUN_SH.read_text(encoding="utf-8")
        self.assertIn('AI33_TTS_WORKERS="${AI33_TTS_WORKERS:-3}"', source)
        self.assertIn("ThreadPoolExecutor(max_workers=ai33_tts_workers)", source)
        self.assertIn("prefetched_tts_results.update(batch_results)", source)
        self.assertIn("for entry_index in range(1, total_entries + 1)", source)
        checkpoint = Path(__file__).with_name("tts_checkpoint.py").read_text(encoding="utf-8")
        self.assertIn("def _manifest_lock", checkpoint)
        self.assertIn("with _manifest_lock(manifest_path)", checkpoint)
        ai33 = Path(__file__).with_name("ai33_tts_synthesize.py").read_text(encoding="utf-8")
        self.assertIn("with tts_checkpoint._manifest_lock(target)", ai33)
        self.assertIn("with tts_checkpoint._manifest_lock(report_path)", ai33)

    def test_prefetch_skips_reusable_checkpoint_cues_without_ramping_above_three(self):
        source = RUN_SH.read_text(encoding="utf-8")
        self.assertIn("reusable_checkpoint_cues", source)
        self.assertIn("if entry_index not in reusable_checkpoint_cues", source)
        self.assertIn('ai33_tts_workers = max(1, min(3, int(os.environ.get("AI33_TTS_WORKERS", "3") or "3")))', source)
        self.assertNotIn("ai33_tts_workers += 1", source)

    def test_prefetch_stops_submitting_batches_after_provider_failure(self):
        source = RUN_SH.read_text(encoding="utf-8")
        self.assertIn(
            'if any((result[0] or {}).get("ai33_failed") for result in batch_results.values()):',
            source,
        )
        self.assertIn('print("AI33 prefetch stopped after provider failure", flush=True)', source)

    def test_voice_qa_retry_forces_only_failed_cues(self):
        source = RUN_SH.read_text(encoding="utf-8")
        self.assertIn("TTS_FORCE_CUE_IDS", source)
        self.assertIn("TTS_SPOKEN_TEXT_OVERRIDES_JSON", source)
        self.assertIn("if entry_index in forced_cue_ids:", source)
        self.assertIn('"$WHISPER_BIN" -m "$WHISPER_MODEL" -f "$VIETNAMESE_VOICE_WAV" -l vi -osrt', source)
        self.assertIn('retry-overrides --report "$TTS_VOICE_QUALITY_REPORT_JSON"', source)
        self.assertIn('TTS_FORCE_CUE_IDS="$tts_qa_failed_cues"', source)
        self.assertIn("tts_qa_ai33=$?", source)
        self.assertIn('"TTSPronunciationQualityFailed"', source)

    def test_auto_bgm_requires_real_demucs_no_vocals_stem(self):
        source = RUN_SH.read_text(encoding="utf-8")
        self.assertIn('BGM_MODE_FALLBACK="${BGM_MODE_FALLBACK:-none}"', source)
        self.assertIn('"BackgroundSeparationFailed"', source)
        self.assertIn('data.get("demucs", {}).get("used") is True', source)
        auto_case = source[source.index("select_bgm_source() {"):source.index("write_fit_adjustments_report() {")]
        self.assertNotIn('else SELECTED_BGM_MODE="duck"; SELECTED_BGM_SOURCE="$VIDEO"', auto_case)

    def test_demucs_keeps_music_bed_stereo_48k(self):
        source = SPEECH_PREPROCESS.read_text(encoding="utf-8")
        self.assertIn("def ffmpeg_extract_demucs_input", source)
        self.assertIn('"2", "-ar", "48000"', source)
        self.assertIn("convert_music_bed(found_no_vocals, no_vocals_wav)", source)
        self.assertIn("demucs_separate(demucs_input", source)

        self.assertIn('SPEECH_ONLY_DEMUCS_CHUNK_SECONDS', source)
        self.assertIn('def demucs_separate_chunked', source)
        self.assertIn('def concat_audio', source)

    def test_ai33_pronunciation_dictionary_reaches_wrapper_and_checkpoint(self):
        source = RUN_SH.read_text(encoding="utf-8")
        self.assertIn("AI33_PRONUNCIATION_DICTIONARY_ID", source)
        self.assertIn("'pronunciation_dictionary_id': ai33_pronunciation_dictionary_id", source)
        self.assertIn("'--pronunciation-dictionary-id', ai33_pronunciation_dictionary_id", source)

    def test_ai33_low_source_sample_rate_retries_only_the_failed_cue_once(self):
        source = RUN_SH.read_text(encoding="utf-8")
        self.assertIn("AI33SourceSampleRateLow", source)
        self.assertIn("AI33WavSilent", source)
        self.assertIn("quality_error_codes", source)
        self.assertIn("AI33_SOURCE_QUALITY_RETRIES", source)
        self.assertIn("cmd.append('--force-regenerate')", source)
        wrapper = Path(__file__).with_name("ai33_tts_synthesize.py").read_text(encoding="utf-8")
        self.assertIn('if error.code != "AI33SourceSampleRateLow":', wrapper)

    def test_each_spoken_cue_is_loudness_normalized_before_concat(self):
        source = RUN_SH.read_text(encoding="utf-8")
        self.assertIn("def normalize_speech_loudness", source)
        self.assertIn("'loudnorm=I=-20:TP=-3:LRA=7,alimiter=limit=0.7079:level=false'", source)
        self.assertIn("if not tts_result.get(\"fallback_silence\"):", source)
        self.assertIn("normalize_speech_loudness(segment_out, segment_index)", source)
        self.assertIn('"loudness_normalized_segments": 0', source)


    def test_vieneu_health_and_wav_synthesis_use_fake_http_with_one_retry(self):
        source = RUN_SH.read_text(encoding="utf-8")
        self.assertIn("def vieneu_health_check", source)
        self.assertIn("def synthesize_vieneu_http", source)
        self.assertIn("VIENEU_STYLE", source)
        self.assertIn('VIENEU_STYLE="${VIENEU_STYLE:-story}"', source)
        self.assertIn('VIENEU_DEFAULT_VOICE="${VIENEU_DEFAULT_VOICE:-hong-chau}"', source)
        self.assertIn("if (voice or '').lower().startswith('vieneu')", source)
        self.assertIn('if [[ "$voice_lower" == vieneu:* ]]; then', source)
        self.assertIn('payload = json.dumps({"text": text, "voice": voice, "style": style})', source)
        self.assertIn('payload.get("ready") is True', source)
        client = source.split("# VIENEU_HTTP_CLIENT_BEGIN\n", 1)[1].split(
            "# VIENEU_HTTP_CLIENT_END", 1
        )[0]
        requests = []
        wav_buffer = __import__("io").BytesIO()
        with wave.open(wav_buffer, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(48000)
            output.writeframes(b"\x00\x02" * 2400)
        wav_bytes = wav_buffer.getvalue()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.assert_path("/health")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ready":true}')

            def do_POST(self):
                self.assert_path("/v1/synthesize")
                length = int(self.headers["Content-Length"])
                requests.append(json.loads(self.rfile.read(length)))
                if len(requests) == 1:
                    self.send_response(503)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(wav_bytes)))
                self.end_headers()
                self.wfile.write(wav_bytes)

            def assert_path(self, expected):
                if self.path != expected:
                    raise AssertionError(f"unexpected path {self.path}")

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "vieneu.wav"
                script = client + """
print(json.dumps({
    "health": vieneu_health_check(sys.argv[1]),
    "result": synthesize_vieneu_http(
        "Xin chao", "vieneu:mai", "documentary", sys.argv[2], sys.argv[1]
    ),
}))
"""
                result = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        script,
                        f"http://127.0.0.1:{server.server_port}",
                        str(output),
                    ],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                payload = json.loads(result.stdout)
                self.assertTrue(payload["health"])
                self.assertEqual(2, payload["result"]["attempts"])
                self.assertEqual("vieneu", payload["result"]["engine"])
                with wave.open(str(output), "rb") as rendered:
                    self.assertEqual((48000, 1, 2), (
                        rendered.getframerate(),
                        rendered.getnchannels(),
                        rendered.getsampwidth(),
                    ))
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

        self.assertEqual(2, len(requests))
        self.assertEqual(
            {"text": "Xin chao", "voice": "vieneu:mai", "style": "documentary"},
            requests[-1],
        )

    def test_vieneu_health_requires_ready_true(self):
        source = RUN_SH.read_text(encoding="utf-8")
        client = source.split("# VIENEU_HTTP_CLIENT_BEGIN\n", 1)[1].split(
            "# VIENEU_HTTP_CLIENT_END", 1
        )[0]

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ready":false}')

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    client + "print(vieneu_health_check(sys.argv[1]))",
                    f"http://127.0.0.1:{server.server_port}",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("False\n", result.stdout)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_vieneu_failure_preserves_provider_error(self):
        source = RUN_SH.read_text(encoding="utf-8")
        client = source.split("# VIENEU_HTTP_CLIENT_BEGIN\n", 1)[1].split(
            "# VIENEU_HTTP_CLIENT_END", 1
        )[0]

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(503)
                self.end_headers()

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "vieneu.wav"
                result = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        client
                        + """
print(json.dumps(synthesize_vieneu_http(
    "Xin chao", "vieneu:hong-chau", "story", sys.argv[2], sys.argv[1]
)))
""",
                        f"http://127.0.0.1:{server.server_port}",
                        str(output),
                    ],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual("VieNeuSynthesisFailed", payload["error_code"])
                self.assertIn("503", payload["error_message"])
                self.assertTrue(payload["vieneu_failed"])
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_vieneu_preflight_falls_back_as_one_provider_or_stops_without_silence(self):
        source = RUN_SH.read_text(encoding="utf-8")
        self.assertIn("prepare_tts_provider || exit 1", source)
        self.assertIn('VOICE="ai33:${AI33_DEFAULT_VOICE_ID}"', source)
        self.assertIn('"VieNeuUnavailable"', source)
        self.assertIn("requested_voice", source)
        self.assertIn("actual_voice", source)
        self.assertIn("voice_fallback_reason", source)
        vieneu_client = source.split(
            "# VIENEU_HTTP_CLIENT_BEGIN\n", 1
        )[1].split("# VIENEU_HTTP_CLIENT_END", 1)[0]
        vieneu_body = vieneu_client[
            vieneu_client.index("def synthesize_vieneu_http")
        :]
        self.assertIn('"fallback_silence": False', vieneu_body)
        self.assertIn('"vieneu_failed": True', vieneu_body)
        self.assertIn('"provider": "vieneu"', source)
        self.assertIn('"backend": "http"', source)

    def test_structured_pipeline_failure_is_not_replaced_by_generic_error(self):
        source = RUN_SH.read_text(encoding="utf-8")
        fail_body = source.split("\nfail() {", 1)[1].split(
            "\nappend_tts_audio_stage_report", 1
        )[0]
        self.assertIn('status.get("error_code")', fail_body)
        self.assertIn('"requested_voice"', source)
        self.assertIn('"actual_voice"', source)

if __name__ == "__main__":
    unittest.main(verbosity=2)
