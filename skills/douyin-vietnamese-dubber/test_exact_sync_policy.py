#!/usr/bin/env python3
"""Regression tests for exact-sync voice fitting and 48 kHz invariants."""

import importlib.util
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, SKILL_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


speed_contract = load("tts_speed_contract")
final_mix = load("final_mix_quality")


class ExactSyncPolicyTests(unittest.TestCase):
    def test_exact_sync_uses_measured_pitch_preserving_residual(self):
        decision = speed_contract.measured_post_atempo_fit(
            actual_duration_ms=1800,
            allowed_duration_ms=1000,
            native_speed=1.12,
            total_max_speed=99,
            routine_post_atempo_max=1.05,
            adaptation_needs_attention=False,
            exact_sync=True,
        )
        self.assertEqual("exact_sync_rescue", decision["decision"])
        self.assertAlmostEqual(1.8, decision["post_atempo_factor"], places=3)
        self.assertAlmostEqual(2.016, decision["total_speed_factor"], places=3)

    def test_canonical_audio_stages_require_48khz_but_provider_input_may_differ(self):
        self.assertIsNone(final_mix.canonical_sample_rate_error("ai33_response", 16000, 48000))
        self.assertEqual(
            "TTS_CANONICAL_SAMPLE_RATE_MISMATCH stage=tts_after_tempo expected=48000 actual=16000",
            final_mix.canonical_sample_rate_error("tts_after_tempo", 16000, 48000),
        )
        self.assertIsNone(final_mix.canonical_sample_rate_error("final_mp4", 48000, 48000))

    def test_exact_sync_runtime_defaults_and_reports_are_wired(self):
        script = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
        required = [
            'SYNC_MODE="${SYNC_MODE:-${TTS_SYNC_MODE:-exact_sync}}"',
            "exact|exact_sync)",
            'TTS_SYNC_POLICY="${TTS_SYNC_POLICY:-frame_strict}"',
            'FRAME_STRICT_MAX_SEGMENT_DRIFT_MS="${FRAME_STRICT_MAX_SEGMENT_DRIFT_MS:-40}"',
            'MAX_FREEZE_PER_SEGMENT_MS="${MAX_FREEZE_PER_SEGMENT_MS:-1500}"',
            'exact_sync = (sync_mode == "exact_sync")',
            "'speech_timing_source': speech_timing_source,",
            "canonical_sample_rate_error",
            "if str(exc).startswith('TTS_CANONICAL_SAMPLE_RATE_MISMATCH'):",
        ]
        self.assertEqual([], [item for item in required if item not in script])
        self.assertNotIn("asetrate", script)

    def test_small_scene_safe_tail_overhang_can_freeze(self):
        decision = final_mix.decide_video_fit(
            video_seconds=60,
            voice_seconds=60.12,
            allow_video_retime=True,
            allow_freeze_frame=True,
            scene_safe=True,
            max_freeze_per_segment_ms=300,
            max_freeze_per_scene_ms=300,
            max_output_duration_increase=1,
        )
        self.assertEqual("tail_freeze_local", decision["action"])
        self.assertEqual(120, decision["freeze_ms"])


if __name__ == "__main__":
    unittest.main()
