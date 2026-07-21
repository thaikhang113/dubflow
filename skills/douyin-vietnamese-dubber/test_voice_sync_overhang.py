#!/usr/bin/env python3
"""Text-free gate coverage for contiguous TTS overhang into the next cue."""
import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILL_DIR))


class VoiceSyncOverhangTests(unittest.TestCase):
    def test_366_and_268_ms_contiguous_overhangs_fail(self):
        from voice_sync_overhang import summarize_unresolved_overhang
        result = summarize_unresolved_overhang([
            {"cue_id": 11, "reason": "next_cue_overlap", "duration_ms": 366},
            {"cue_id": 12, "reason": "next_cue_overlap", "duration_ms": 268},
        ], "120")
        self.assertTrue(result["failed"])
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["max_ms"], 366)
        self.assertEqual(result["reasons"], [
            {"cue_id": 11, "reason": "next_cue_overlap", "duration_ms": 366},
            {"cue_id": 12, "reason": "next_cue_overlap", "duration_ms": 268},
        ])

    def test_overhang_at_or_below_120_ms_passes(self):
        from voice_sync_overhang import summarize_unresolved_overhang
        result = summarize_unresolved_overhang([
            {"cue_id": 11, "reason": "next_cue_overlap", "duration_ms": 120},
        ], "120")
        self.assertFalse(result["failed"])

    def test_fractional_overhang_uses_an_explicit_positive_millisecond_ceiling(self):
        from voice_sync_overhang import unresolved_overhang_event, summarize_unresolved_overhang
        self.assertEqual(
            unresolved_overhang_event(11, actual_end_ms=1119.9, next_start_ms=1000),
            {"cue_id": 11, "reason": "next_cue_overlap", "duration_ms": 120},
        )
        self.assertFalse(summarize_unresolved_overhang([
            unresolved_overhang_event(11, actual_end_ms=1120.0, next_start_ms=1000),
        ], 120)["failed"])
        self.assertTrue(summarize_unresolved_overhang([
            unresolved_overhang_event(11, actual_end_ms=1120.1, next_start_ms=1000),
        ], 120)["failed"])

    def test_source_gap_absorbed_overhang_has_no_event(self):
        from voice_sync_overhang import unresolved_overhang_event
        self.assertIsNone(unresolved_overhang_event(11, actual_end_ms=1500, next_start_ms=1500))

    def test_post_fit_audio_only_flags_overlap_with_the_contiguous_next_cue(self):
        from voice_sync_overhang import unresolved_overhang_event
        event = unresolved_overhang_event(11, actual_end_ms=1200, next_start_ms=1000)
        self.assertEqual(event["cue_id"], 11)
        self.assertEqual(event["duration_ms"], 200)

    def test_overhang_event_keeps_group_source_ids_without_using_them_as_cue_identity(self):
        from voice_sync_overhang import unresolved_overhang_event
        self.assertEqual(
            unresolved_overhang_event(4, 1200, 1000, source_cue_ids=[41, 77]),
            {"cue_id": 4, "reason": "next_cue_overlap", "duration_ms": 200,
             "source_cue_ids": [41, 77]},
        )

    def test_final_tail_has_no_next_cue_event(self):
        from voice_sync_overhang import unresolved_overhang_event
        self.assertIsNone(unresolved_overhang_event(11, actual_end_ms=1500, next_start_ms=None))

    def test_invalid_threshold_uses_nonnegative_default(self):
        from voice_sync_overhang import summarize_unresolved_overhang
        result = summarize_unresolved_overhang([], "not-a-number")
        self.assertEqual(result["threshold_ms"], 120)

    def test_internal_gate_exception_maps_to_needs_attention_and_blocks_organization(self):
        from voice_sync_status import gate_terminal_status
        self.assertEqual(gate_terminal_status(9), {
            "status": "needs_attention",
            "error_code": "VoiceSyncGateInternalError",
            "block_organization": True,
        })

    def test_missing_or_unreadable_voice_sync_report_blocks_organization(self):
        from voice_sync_status import final_report_status
        self.assertEqual(final_report_status(None), {
            "status": "needs_attention",
            "error_code": "VoiceSyncReportMissing",
            "message": "Thiếu voice_sync_quality_report.json sau TTS/render; không organize output.",
            "block_organization": True,
        })
        self.assertEqual(final_report_status("not-json")["error_code"], "VoiceSyncReportUnreadable")

    def test_explicit_voice_sync_report_statuses_keep_existing_semantics(self):
        from voice_sync_status import final_report_status
        self.assertIsNone(final_report_status('{"status":"ok"}'))
        self.assertIsNone(final_report_status('{"status":"warning"}'))
        self.assertEqual(final_report_status('{"status":"fail"}')["status"], "needs_attention")


if __name__ == "__main__":
    unittest.main()
