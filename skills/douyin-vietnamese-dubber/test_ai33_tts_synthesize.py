#!/usr/bin/env python3
"""Offline regression tests for AI33 task polling error handling."""

import contextlib
import importlib.util
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import os
import sys
from pathlib import Path
from unittest.mock import patch


SKILL_DIR = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ai33_tts_synthesize", SKILL_DIR / "ai33_tts_synthesize.py")
ai33 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ai33)


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class AI33PollingTests(unittest.TestCase):
    def test_speed_contract_keeps_native_and_total_caps_distinct_for_measured_rescue(self):
        """A 1.12 provider request may use only the measured residual up to 1.35x total."""
        speed_contract_path = SKILL_DIR / "tts_speed_contract.py"
        spec = importlib.util.spec_from_file_location("tts_speed_contract_rescue", speed_contract_path)
        contract = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(contract)

        plan = contract.canonical_speed_contract(
            1.30, native_max_speed=1.12, total_max_speed=1.35,
            residual_atempo_max=1.05, measured_overlong=True,
        )
        self.assertEqual(1.12, plan["native_speed"])
        self.assertGreater(plan["post_atempo_max"], 1.0)
        self.assertLessEqual(plan["total_speed_factor"], 1.35)
        self.assertAlmostEqual(1.30, plan["total_speed_factor"], places=4)

    def test_measured_overlong_fit_is_available_after_rejected_adaptation_without_rewrite_acceptance(self):
        """Semantic rejection remains visible while text-preserving audio rescue stays bounded."""
        speed_contract_path = SKILL_DIR / "tts_speed_contract.py"
        spec = importlib.util.spec_from_file_location("tts_speed_contract_rejected", speed_contract_path)
        contract = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(contract)

        decision = contract.measured_post_atempo_fit(
            actual_duration_ms=1300, allowed_duration_ms=1000,
            native_speed=1.12, total_max_speed=1.35, routine_post_atempo_max=1.05,
            adaptation_needs_attention=True,
        )
        self.assertEqual("measured_overlong_rescue", decision["decision"])
        self.assertTrue(decision["adaptation_needs_attention"])
        self.assertGreater(decision["post_atempo_factor"], 1.05)
        self.assertLessEqual(decision["total_speed_factor"], 1.35)

    def test_measured_overlong_fit_rescues_accepted_candidate_without_fabricating_semantic_attention(self):
        """Accepted pending-fit text may consume bounded residual audio speed."""
        speed_contract_path = SKILL_DIR / "tts_speed_contract.py"
        spec = importlib.util.spec_from_file_location("tts_speed_contract_accepted", speed_contract_path)
        contract = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(contract)

        decision = contract.measured_post_atempo_fit(
            actual_duration_ms=3070, allowed_duration_ms=2020,
            native_speed=1.12, total_max_speed=1.35, routine_post_atempo_max=1.05,
            adaptation_needs_attention=False, adaptation_fit_eligible=True,
        )
        self.assertEqual("measured_overlong_rescue", decision["decision"])
        self.assertAlmostEqual(1.205357, decision["post_atempo_factor"], places=4)
        self.assertLessEqual(decision["total_speed_factor"], 1.35)
        self.assertFalse(decision["adaptation_needs_attention"])

    def test_measured_rescue_replays_72_cue_overlong_fixture_without_relaxing_gates(self):
        """Nine current overlong cues fall to <=7 and drift <=500 using only bounded audio fit."""
        speed_contract_path = SKILL_DIR / "tts_speed_contract.py"
        spec = importlib.util.spec_from_file_location("tts_speed_contract_fixture", speed_contract_path)
        contract = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(contract)

        # Numeric-only fixture: 63 fitting cues, seven 1.30x and two 1.50x
        # measured overlong cues.  The original report's max drift was 1070ms.
        durations = [1000] * 63 + [1300] * 7 + [1500] * 2
        fitted = []
        totals = []
        for duration in durations:
            result = contract.measured_post_atempo_fit(
                actual_duration_ms=duration, allowed_duration_ms=1000,
                native_speed=1.12, total_max_speed=1.35, routine_post_atempo_max=1.05,
                adaptation_needs_attention=duration > 1000,
            )
            fitted.append(duration / result["post_atempo_factor"])
            totals.append(result["total_speed_factor"])
        too_long = sum(duration > 1120 for duration in fitted)  # existing 120ms overhang allowance
        self.assertLessEqual(too_long, 7)
        self.assertLessEqual(max(duration - 1000 for duration in fitted), 500)
        self.assertTrue(all(total <= 1.35 for total in totals))

    def test_routine_fit_retains_gentle_post_cap_and_needs_measured_overlong_to_escalate(self):
        speed_contract_path = SKILL_DIR / "tts_speed_contract.py"
        spec = importlib.util.spec_from_file_location("tts_speed_contract_routine", speed_contract_path)
        contract = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(contract)

        routine = contract.measured_post_atempo_fit(
            actual_duration_ms=1040, allowed_duration_ms=1000,
            native_speed=1.12, total_max_speed=1.35, routine_post_atempo_max=1.05,
            adaptation_needs_attention=False,
        )
        self.assertEqual("routine_fit", routine["decision"])
        self.assertEqual(1.04, routine["post_atempo_factor"])
        self.assertLessEqual(routine["post_atempo_factor"], 1.05)

    def test_speed_contract_models_13_of_72_and_15_of_70_without_double_speed(self):
        """Historical overhang fixtures either converge safely or remain needs-attention."""
        speed_contract_path = SKILL_DIR / "tts_speed_contract.py"
        spec = importlib.util.spec_from_file_location("tts_speed_contract", speed_contract_path)
        contract = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(contract)

        # 13/72 and 15/70 were historical too-long counts.  The fixture contains
        # only timing factors, never subtitle text or job content.
        for cue_count, overlong_count, requested in ((72, 13, 1.10), (70, 15, 1.18)):
            plans = [contract.canonical_speed_contract(
                requested if index < overlong_count else 1.0,
                native_max_speed=1.12,
                total_max_speed=1.12,
                residual_atempo_max=1.03,
            ) for index in range(cue_count)]
            self.assertTrue(all(plan["total_speed_factor"] <= 1.12 for plan in plans))
            self.assertTrue(all(plan["post_atempo_max"] == 1.0 for plan in plans))
            self.assertEqual(overlong_count, sum(plan["native_speed"] > 1.0 for plan in plans))
            self.assertEqual("numeric", plans[0]["native_speed_mode"])
            unresolved = sum(
                requested > plan["total_speed_factor"] + 0.0005
                for plan in plans[:overlong_count]
            )
            self.assertEqual(0 if cue_count == 72 else 15, unresolved)

        # If the native provider limit is lower than the total quality budget,
        # atempo is only the measured residual and never the full request again.
        residual = contract.canonical_speed_contract(
            1.12, native_max_speed=1.10, total_max_speed=1.12,
            residual_atempo_max=1.03,
        )
        self.assertEqual((1.10, 1.0182, 1.12), (
            residual["native_speed"], residual["post_atempo_max"], residual["total_speed_factor"],
        ))

    def test_48k_conversion_uses_resample_without_pitch_filter(self):
        runs = []
        with patch.object(ai33.subprocess, "run", side_effect=lambda *args, **kwargs: runs.append(args[0]) or type("P", (), {"stdout": "0.5"})()):
            ai33.convert_to_wav(Path("input.mp3"), Path("output.wav"), 48000, 1)
        conversion = runs[0]
        self.assertIn("aresample=48000", conversion)
        self.assertNotIn("asetrate", conversion)

    def test_44k1_source_is_accepted_for_48k_output_resampling(self):
        ai33.validate_source_audio(
            {"codec": "mp3", "duration_ms": 1000, "sample_rate": 44100},
            requested_sample_rate=48000,
            attempts=1,
            voice_id="vbee_hn_female_ngochuyen_full_48k-fhg",
        )

    def test_source_below_44k1_is_rejected_for_48k_voice(self):
        with self.assertRaises(ai33.AI33Error) as raised:
            ai33.validate_source_audio(
                {"codec": "mp3", "duration_ms": 1000, "sample_rate": 32000},
                requested_sample_rate=48000,
                attempts=1,
                voice_id="vbee_hn_female_ngochuyen_full_48k-fhg",
            )
        self.assertEqual("AI33SourceSampleRateLow", raised.exception.code)
        self.assertEqual("source_quality", raised.exception.stage)
        self.assertNotIn("http", raised.exception.detail.lower())

    def test_native_24k_voice_is_accepted_for_48k_output_resampling(self):
        ai33.validate_source_audio(
            {"codec": "mp3", "duration_ms": 1000, "sample_rate": 24000},
            requested_sample_rate=48000,
            attempts=1,
            voice_id="vbee_hn_female_ngochuyen_full_24k-st",
        )

    def test_polling_busy_429_retries_then_returns_completed_task(self):
        busy = urllib.error.HTTPError(
            "https://example.invalid/v1/task/task-1",
            429,
            "Too Many Requests",
            {},
            io.BytesIO(b'{"success":false,"message":"Task polling temporarily busy"}'),
        )
        responses = [busy, FakeResponse({"success": True, "data": {"status": "completed", "audio_url": "https://cdn.example/audio.mp3"}})]
        sleeps = []

        def urlopen(*_args, **_kwargs):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        with patch.object(ai33.urllib.request, "urlopen", side_effect=urlopen), \
             patch.object(ai33.time, "sleep", side_effect=sleeps.append):
            result = ai33.poll_task("https://example.invalid", {}, "task-1", timeout_total=30, poll_interval=0.25)

        self.assertEqual("https://cdn.example/audio.mp3", ai33.find_audio_url(result))
        self.assertEqual(1, len(sleeps))
        self.assertGreaterEqual(sleeps[0], 0.25)

    def test_true_quota_429_is_classified_without_exiting_process(self):
        quota = urllib.error.HTTPError(
            "https://example.invalid/v1/task/task-1",
            429,
            "Too Many Requests",
            {},
            io.BytesIO(b'{"success":false,"message":"Insufficient credit"}'),
        )
        with patch.object(ai33.urllib.request, "urlopen", side_effect=quota), \
             self.assertRaises(ai33.AI33Error) as raised:
            ai33.get_json("https://example.invalid/v1/task/task-1", {}, timeout=1)

        self.assertEqual(ai33.MARKER_QUOTA, raised.exception.code)
        self.assertNotIn("example.invalid", raised.exception.detail)


class AI33ResilienceTests(unittest.TestCase):
    def _http(self, code):
        return urllib.error.HTTPError("https://cdn.example/signed", code, "error", {}, io.BytesIO(b"no details"))

    def _main_args(self, output: Path):
        return ["ai33", "--text", "hello", "--voice", "voice", "--output", str(output)]

    def _download_fixture(self, _url, destination, *_args, **_kwargs):
        Path(destination).write_bytes(b"ID3" + b"x" * 300)
        return 1

    def test_create_429_updates_circuit_breaker_instead_of_exiting_worker(self):
        quota = urllib.error.HTTPError(
            "https://example.invalid/v3/text-to-speech",
            429,
            "Too Many Requests",
            {},
            io.BytesIO(b'{"message":"Insufficient credit"}'),
        )
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "out.wav"
            provider_state = Path(td) / "provider.json"
            args = self._main_args(output) + ["--provider-state", str(provider_state)]
            with patch.dict(os.environ, {"AI33_API_KEY": "test-token"}, clear=False), \
                 patch.object(sys, "argv", args), \
                 patch.object(ai33.urllib.request, "urlopen", side_effect=quota), \
                 contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(3, ai33.main())

            state = json.loads(provider_state.read_text(encoding="utf-8"))
            self.assertEqual("open", state["state"])
            self.assertEqual(ai33.MARKER_QUOTA, state["open_code"])

    def test_atomic_conversion_passes_ffmpeg_a_wav_suffixed_temporary_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); output = root / "out.wav"; converted = []

            def convert(_src, wav, sample_rate, channels):
                converted.append(wav)
                self.assertEqual(".wav", wav.suffix)
                ai33.write_test_wav(wav, sample_rate, [100] * 480, channels)
                return 10.0

            with patch.dict(os.environ, {"AI33_API_KEY": "test-token"}, clear=False), \
                 patch.object(sys, "argv", self._main_args(output)), \
                 patch.object(ai33, "create_task", return_value={"audio_url": "https://cdn.example/audio.mp3"}), \
                 patch.object(ai33, "download_with_retry", side_effect=self._download_fixture), \
                 patch.object(ai33, "audio_info", return_value={"codec": "mp3", "duration_ms": 10}), \
                 patch.object(ai33, "convert_to_wav", side_effect=convert), \
                 patch.object(ai33, "append_audio_report"):
                self.assertEqual(0, ai33.main())

            self.assertEqual(1, len(converted))
            self.assertTrue(output.exists())
            self.assertEqual([], list(root.glob("out.wav.tmp-*.wav")))

    def test_atomic_conversion_cleans_wav_temp_when_validation_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); output = root / "out.wav"

            def convert(_src, wav, sample_rate, channels):
                ai33.write_test_wav(wav, sample_rate, [100] * 480, channels)
                return 10.0

            with patch.dict(os.environ, {"AI33_API_KEY": "test-token"}, clear=False), \
                 patch.object(sys, "argv", self._main_args(output)), \
                 patch.object(ai33, "create_task", return_value={"audio_url": "https://cdn.example/audio.mp3"}), \
                 patch.object(ai33, "download_with_retry", side_effect=self._download_fixture), \
                 patch.object(ai33, "audio_info", return_value={"codec": "mp3", "duration_ms": 10}), \
                 patch.object(ai33, "convert_to_wav", side_effect=convert), \
                 patch.object(ai33, "validate_wav", side_effect=ai33.AI33Error("AI33WavInvalid", "wav_validate")), \
                 patch.object(ai33, "append_audio_report"), \
                 contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(6, ai33.main())

            self.assertFalse(output.exists())
            self.assertEqual([], list(root.glob("out.wav.tmp-*.wav")))

    def test_download_500_retries_then_succeeds_without_url_in_error(self):
        calls = []
        class BytesResponse:
            status = 200
            def read(self): return b"ID3" + b"x" * 300
            def __enter__(self): return self
            def __exit__(self, *_): return False
        with tempfile.TemporaryDirectory() as td, \
             patch.object(ai33.urllib.request, "urlopen", side_effect=[self._http(500), BytesResponse()]), \
             patch.object(ai33.time, "sleep", side_effect=lambda delay: calls.append(delay)):
            ai33.download_with_retry("https://cdn.example/signed?secret=never-log", Path(td) / "audio.src", 1, 3, 30)
        self.assertEqual(1, len(calls))

    def test_download_retry_refreshes_same_task_url_before_next_attempt(self):
        class BytesResponse:
            status = 200
            def read(self): return b"ID3" + b"x" * 300
            def __enter__(self): return self
            def __exit__(self, *_): return False
        refreshed = []
        with tempfile.TemporaryDirectory() as td, \
             patch.object(ai33.urllib.request, "urlopen", side_effect=[self._http(500), BytesResponse()]) as opened, \
             patch.object(ai33.time, "sleep"):
            attempts = ai33.download_with_retry(
                "https://cdn.example/expired", Path(td) / "audio.src", 1, 3, 30,
                refresh_url=lambda: refreshed.append(True) or "https://cdn.example/fresh",
            )
        self.assertEqual(2, attempts)
        self.assertEqual([True], refreshed)
        self.assertIn("https://cdn.example/fresh", opened.call_args_list[1].args[0].full_url)

    def test_download_401_does_not_retry(self):
        with tempfile.TemporaryDirectory() as td, \
             patch.object(ai33.urllib.request, "urlopen", side_effect=self._http(401)) as opened, \
             self.assertRaises(ai33.AI33Error) as raised:
            ai33.download_with_retry("https://cdn.example/signed", Path(td) / "audio.src", 1, 3, 30)
        self.assertEqual("AI33DownloadHttp4xx", raised.exception.code)
        self.assertEqual(1, opened.call_count)

    def test_download_429_and_timeout_retry(self):
        class BytesResponse:
            status = 200
            def read(self): return b"ID3" + b"x" * 300
            def __enter__(self): return self
            def __exit__(self, *_): return False
        with tempfile.TemporaryDirectory() as td, \
             patch.object(ai33.urllib.request, "urlopen", side_effect=[self._http(429), TimeoutError("timed out"), BytesResponse()]), \
             patch.object(ai33.time, "sleep") as sleeper:
            attempts = ai33.download_with_retry("https://cdn.example/signed", Path(td) / "audio.src", 1, 3, 30)
        self.assertEqual(3, attempts); self.assertEqual(2, sleeper.call_count)

    def test_connection_reset_retries_and_exhaustion_keeps_precise_code(self):
        class BytesResponse:
            status = 200
            def read(self): return b"ID3" + b"x" * 300
            def __enter__(self): return self
            def __exit__(self, *_): return False
        reset = urllib.error.URLError(ConnectionResetError("connection reset"))
        with tempfile.TemporaryDirectory() as td, patch.object(ai33.urllib.request, "urlopen", side_effect=[reset, BytesResponse()]), patch.object(ai33.time, "sleep"):
            self.assertEqual(2, ai33.download_with_retry("https://cdn.example/signed", Path(td) / "audio.src", 1, 2, 30))
        with tempfile.TemporaryDirectory() as td, patch.object(ai33.urllib.request, "urlopen", side_effect=[self._http(500), self._http(500)]), patch.object(ai33.time, "sleep"), self.assertRaises(ai33.AI33Error) as raised:
            ai33.download_with_retry("https://cdn.example/signed", Path(td) / "audio.src", 1, 2, 30)
        self.assertEqual("AI33DownloadHttp5xx", raised.exception.code)
        self.assertEqual(2, raised.exception.attempts)

    def test_empty_download_is_terminal_and_checkpoint_write_cleans_temp_on_failure(self):
        class EmptyResponse:
            status = 200
            def read(self): return b""
            def __enter__(self): return self
            def __exit__(self, *_): return False
        with tempfile.TemporaryDirectory() as td, patch.object(ai33.urllib.request, "urlopen", return_value=EmptyResponse()) as opened, self.assertRaises(ai33.AI33Error) as raised:
            ai33.download_with_retry("https://cdn.example/signed", Path(td) / "audio.src", 1, 3, 30)
        self.assertEqual("AI33DownloadEmpty", raised.exception.code); self.assertEqual(1, opened.call_count)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "checkpoint.json"
            with patch.object(ai33.os, "replace", side_effect=OSError("interrupted")):
                with self.assertRaises(OSError): ai33._atomic_json(path, {"schema_version": 1})
            self.assertFalse(path.exists())
            self.assertEqual([], list(Path(td).glob("checkpoint.json.tmp-*")))

    def test_signed_urls_are_redacted_from_debug_payloads(self):
        self.assertEqual("<redacted-url>", ai33._redact({"audio_url": "https://cdn.example/file?signature=secret"})["audio_url"])

    def test_checkpoint_reuses_only_matching_valid_wav(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            wav = root / "cue.wav"
            ai33.write_test_wav(wav, sample_rate=48000, samples=[100] * 480)
            manifest = root / "tts_checkpoint.json"
            cue = ai33.complete_checkpoint_cue(manifest, 1, "source", "text-a", "voice", "settings", wav, 48000, 1, attempts=1, total_cues=122)
            self.assertEqual(122, json.loads(manifest.read_text(encoding="utf-8"))["total_cues"])
            self.assertTrue(ai33.reusable_checkpoint_cue(manifest, 1, "source", "text-a", "voice", "settings", 48000, 1))
            self.assertFalse(ai33.reusable_checkpoint_cue(manifest, 1, "source", "text-b", "voice", "settings", 48000, 1))
            self.assertFalse(ai33.reusable_checkpoint_cue(manifest, 1, "source", "text-a", "other-voice", "settings", 48000, 1))
            self.assertFalse(ai33.reusable_checkpoint_cue(manifest, 1, "source", "text-a", "voice", "other-speed", 48000, 1))
            wav.unlink()
            self.assertFalse(ai33.reusable_checkpoint_cue(manifest, 1, "source", "text-a", "voice", "settings", 48000, 1))

    def test_reused_checkpoint_materializes_requested_output_without_provider_call(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            saved = root / "saved.wav"; output = root / "segments" / "0001_speech.wav"
            ai33.write_test_wav(saved, 48000, [100] * 480)
            manifest = root / "tts_checkpoint.json"
            ai33.complete_checkpoint_cue(manifest, 1, "source", ai33.hashlib.sha256(b"hello").hexdigest(), "voice", "settings", saved, 48000, 1, 1)
            argv = ["ai33", "--text", "hello", "--voice", "voice", "--output", str(output), "--checkpoint", str(manifest), "--cue-index", "1", "--source-fingerprint", "source", "--settings-fingerprint", "settings"]
            with patch.dict(os.environ, {"AI33_API_KEY": "test-token"}, clear=False), patch.object(sys, "argv", argv), patch.object(ai33, "create_task") as create:
                self.assertEqual(0, ai33.main())
            self.assertTrue(output.exists())
            self.assertEqual(ai33._sha256(saved), ai33._sha256(output))
            create.assert_not_called()

    def test_create_failure_records_redacted_failed_checkpoint(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); manifest = root / "tts_checkpoint.json"; output = root / "out.wav"
            argv = ["ai33", "--text", "hello", "--voice", "voice", "--output", str(output), "--checkpoint", str(manifest), "--cue-index", "1", "--source-fingerprint", "source", "--settings-fingerprint", "settings"]
            with patch.dict(os.environ, {"AI33_API_KEY": "test-token"}, clear=False), patch.object(sys, "argv", argv), patch.object(ai33, "create_task", side_effect=RuntimeError("https://cdn.invalid/secret")), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(3, ai33.main())
            cue = json.loads(manifest.read_text(encoding="utf-8"))["cues"]["0"]
            self.assertEqual("failed", cue["status"])
            self.assertEqual("AI33CreateHttp5xx", cue["error_code"])

    def test_missing_auth_records_precise_checkpoint_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); manifest = root / "tts_checkpoint.json"; output = root / "out.wav"
            argv = ["ai33", "--text", "hello", "--voice", "voice", "--output", str(output), "--checkpoint", str(manifest), "--cue-index", "1", "--total-cues", "1", "--source-fingerprint", "source", "--settings-fingerprint", "settings"]
            with patch.dict(os.environ, {"AI33_API_KEY": "", "AI33_ACCESS_TOKEN": ""}, clear=False), patch.object(sys, "argv", argv), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(3, ai33.main())
            cue = json.loads(manifest.read_text(encoding="utf-8"))["cues"]["0"]
            self.assertEqual(("failed", "auth", "AI33AuthMissing", 0), (cue["status"], cue["stage"], cue["error_code"], cue["attempts"]))

    def test_silent_or_wrong_rate_wav_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            silent = root / "silent.wav"; ai33.write_test_wav(silent, 48000, [0] * 480)
            bad_rate = root / "rate.wav"; ai33.write_test_wav(bad_rate, 16000, [100] * 480)
            with self.assertRaises(ai33.AI33Error) as silent_error:
                ai33.validate_wav(silent, 48000, 1)
            self.assertEqual("AI33WavSilent", silent_error.exception.code)
            with self.assertRaises(ai33.AI33Error) as rate_error:
                ai33.validate_wav(bad_rate, 48000, 1)
            self.assertEqual("AI33WavInvalid", rate_error.exception.code)

    def test_122_cue_resume_reuses_1_through_86_and_starts_at_87(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); manifest = root / "tts_checkpoint.json"
            for cue_index in range(1, 87):
                wav = root / f"{cue_index}.wav"; ai33.write_test_wav(wav, 48000, [100] * 480)
                ai33.complete_checkpoint_cue(manifest, cue_index, "source", f"text-{cue_index}", "voice", "settings", wav, 48000, 1, 1)
            provider_calls = []
            for cue_index in range(1, 123):
                reused = ai33.reusable_checkpoint_cue(manifest, cue_index, "source", f"text-{cue_index}", "voice", "settings", 48000, 1)
                if not reused: provider_calls.append(cue_index)
            self.assertEqual(list(range(87, 123)), provider_calls)


class AI33CircuitBreakerContractTests(unittest.TestCase):
    def test_half_open_transition_is_serialized_across_callers(self):
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "state.json"
            clock = [10.0]
            seed = ai33.AI33CircuitBreaker(state, threshold=1, cooldown_seconds=5, now=lambda: clock[0])
            seed.record_failure(ai33.AI33Error("AI33DownloadNetwork", "download"))
            clock[0] = 16.0
            results = []
            barrier = threading.Barrier(2)

            def probe():
                breaker = ai33.AI33CircuitBreaker(state, threshold=1, cooldown_seconds=5, now=lambda: clock[0])
                barrier.wait()
                try:
                    results.append(("ok", breaker.before_create()))
                except ai33.AI33Error as exc:
                    results.append((exc.code, exc.detail))

            workers = [threading.Thread(target=probe), threading.Thread(target=probe)]
            for worker in workers: worker.start()
            for worker in workers: worker.join()
            self.assertEqual(1, results.count(("ok", True)))
            self.assertIn(("AI33CircuitOpen", "half_open_probe_in_flight"), results)
    def test_sequential_jobs_keep_ai33_state_scoped_and_half_open_once(self):
        """Jobs 48/83/122: a recovered CDN retry stays closed; threshold gates later creates."""
        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "job-48-ai33-health.json"
            clock = [100.0]
            breaker = ai33.AI33CircuitBreaker(state_path, threshold=2, cooldown_seconds=30, now=lambda: clock[0])

            # Job 48: a 429 download that succeeds on the local retry never opens the provider.
            breaker.before_create()
            breaker.record_success()
            self.assertEqual("closed", breaker.snapshot()["state"])

            # Job 83: bounded consecutive transient failures open at the configured threshold.
            breaker.before_create()
            breaker.record_failure(ai33.AI33Error("AI33DownloadHttp5xx", "download", attempts=2))
            self.assertEqual("closed", breaker.snapshot()["state"])
            breaker.before_create()
            breaker.record_failure(ai33.AI33Error("AI33DownloadRateLimited", "download", attempts=2))
            self.assertEqual("open", breaker.snapshot()["state"])

            # Job 122 is blocked before a new task is created and has no silent/voice fallback path.
            with self.assertRaises(ai33.AI33Error) as blocked:
                breaker.before_create()
            self.assertEqual("AI33CircuitOpen", blocked.exception.code)
            self.assertEqual("circuit", blocked.exception.stage)

            # Cooldown permits exactly one probe. It succeeds and clears the failure history.
            clock[0] += 31
            self.assertTrue(breaker.before_create())
            with self.assertRaises(ai33.AI33Error) as second_probe:
                breaker.before_create()
            self.assertEqual("AI33CircuitOpen", second_probe.exception.code)
            breaker.record_success()
            self.assertEqual(("closed", 0), (breaker.snapshot()["state"], breaker.snapshot()["consecutive_transient_failures"]))

    def test_auth_opens_immediately_and_state_never_contains_credentials(self):
        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "ai33_provider_state.json"
            breaker = ai33.AI33CircuitBreaker(state_path, threshold=9, cooldown_seconds=30, now=lambda: 1.0)
            breaker.before_create()
            breaker.record_failure(ai33.AI33Error("AI33AuthMissing", "auth", "token=do-not-save"))
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(("open", "AI33AuthMissing"), (state["state"], state["open_code"]))
            self.assertNotIn("do-not-save", json.dumps(state))

    def test_open_circuit_blocks_wrapper_before_create_and_preserves_checkpoint(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); state = root / "ai33_provider_state.json"; checkpoint = root / "tts_checkpoint.json"
            checkpoint.write_text(json.dumps({"schema_version": 1, "cues": {}}), encoding="utf-8")
            breaker = ai33.AI33CircuitBreaker(state, threshold=1, cooldown_seconds=60)
            breaker.record_failure(ai33.AI33Error("AI33DownloadHttp5xx", "download", attempts=2))
            argv = ["ai33", "--text", "hello", "--voice", "unchanged-voice", "--output", str(root / "out.wav"), "--checkpoint", str(checkpoint), "--cue-index", "122", "--total-cues", "122", "--provider-state", str(state)]
            with patch.dict(os.environ, {"AI33_API_KEY": "test-token"}, clear=False), patch.object(sys, "argv", argv), patch.object(ai33, "create_task") as create, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(3, ai33.main())
            create.assert_not_called()
            self.assertTrue(checkpoint.exists())
            self.assertFalse((root / "out.wav").exists())

    def test_status_contract_reports_retry_and_waiting_provider_fields(self):
        with tempfile.TemporaryDirectory() as td:
            status = Path(td) / "job_status.json"
            error = ai33.AI33Error("AI33DownloadRateLimited", "download", attempts=2)
            ai33.write_provider_status(str(status), "retrying", 122, 122, error, reused=86)
            document = json.loads(status.read_text(encoding="utf-8"))
            self.assertEqual(("retrying", 121, 122, 86, 122, "download", "AI33DownloadRateLimited", 2, 122),
                             (document["phase"], document["tts_cues_completed"], document["tts_cues_total"], document["tts_cues_reused"], document["failed_cue"], document["failed_stage"], document["failed_code"], document["failed_attempts"], document["resume_from_cue"]))

    def test_half_open_probe_failure_reopens_circuit(self):
        with tempfile.TemporaryDirectory() as td:
            clock = [1.0]
            breaker = ai33.AI33CircuitBreaker(Path(td) / "state.json", threshold=1, cooldown_seconds=5, now=lambda: clock[0])
            breaker.record_failure(ai33.AI33Error("AI33DownloadNetwork", "download", attempts=2))
            clock[0] = 7.0
            self.assertTrue(breaker.before_create())
            breaker.record_failure(ai33.AI33Error("AI33DownloadNetwork", "download", attempts=2))
            self.assertEqual("open", breaker.snapshot()["state"])

if __name__ == "__main__":
    unittest.main()
