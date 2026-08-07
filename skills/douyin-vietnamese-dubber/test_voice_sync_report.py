#!/usr/bin/env python3
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILL_DIR))


class VoiceSyncReportTests(unittest.TestCase):
    def test_ai33_stats_without_resona_metadata_use_empty_groups(self):
        from voice_sync_status import normalize_resona_grouped_source_cue_ids

        self.assertEqual(normalize_resona_grouped_source_cue_ids({}), [])
        self.assertEqual(
            normalize_resona_grouped_source_cue_ids(
                {"resona_short_grouped_source_cue_ids": None}
            ),
            [],
        )

    def test_resona_group_metadata_is_read_from_serialized_stats(self):
        from voice_sync_status import normalize_resona_grouped_source_cue_ids

        self.assertEqual(
            normalize_resona_grouped_source_cue_ids(
                {"resona_short_grouped_source_cue_ids": [[1, 2], [4]]}
            ),
            [[1, 2], [4]],
        )

    def test_invalid_serialized_group_metadata_is_safe(self):
        from voice_sync_status import normalize_resona_grouped_source_cue_ids

        self.assertEqual(
            normalize_resona_grouped_source_cue_ids(
                {"resona_short_grouped_source_cue_ids": "not-a-list"}
            ),
            [],
        )

    def test_fallback_report_has_actionable_error(self):
        from voice_sync_status import build_voice_sync_fallback_report

        report = build_voice_sync_fallback_report(
            "NameError: local checker variable", stats_available=True
        )
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["error_code"], "VoiceSyncReportBuildFailed")
        self.assertTrue(report["block_organization"])
        self.assertNotIn("NameError", report["error_message"])

    def test_run_sh_removes_process_local_resona_dependency(self):
        source = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
        checker_start = source.index("stats_path, video_duration, voice_duration")
        checker = source[checker_start:source.index("tts_gate_status=$?", checker_start)]
        self.assertNotIn("resona_tts_group_meta.items()", checker)
        self.assertIn("normalize_resona_grouped_source_cue_ids", checker)
        self.assertIn("serialized_resona_grouped_source_cue_ids", checker)
        self.assertIn("VoiceSyncReportBuildFailed", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
