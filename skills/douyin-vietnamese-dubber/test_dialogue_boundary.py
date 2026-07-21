#!/usr/bin/env python3
"""Regression coverage for text-safe dialogue grouping and overhang gates."""
import importlib.util
import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILL_DIR))


class DialogueBoundaryTests(unittest.TestCase):
    def test_terminal_question_answer_at_zero_gap_never_merges(self):
        from dialogue_boundary import boundary_after
        self.assertEqual(boundary_after("你去哪？"), "terminal_punctuation")

    def test_unpunctuated_chinese_question_at_utterance_end_is_hard_boundary(self):
        from dialogue_boundary import boundary_after
        self.assertEqual(boundary_after("你在哪"), "chinese_question_ending")

    def test_ordinary_nonterminal_fragment_has_no_hard_boundary(self):
        from dialogue_boundary import boundary_after
        self.assertIsNone(boundary_after("我刚才想说"))

    def test_colon_and_semicolon_continue_but_sentence_terminals_do_not(self):
        from dialogue_boundary import boundary_after
        self.assertIsNone(boundary_after("他说："))
        self.assertIsNone(boundary_after("先这样；"))
        self.assertEqual(boundary_after("先这样。"), "terminal_punctuation")
        self.assertEqual(boundary_after("真的……"), "terminal_punctuation")

    def test_question_suffixes_handle_closing_quotes_and_brackets_conservatively(self):
        from dialogue_boundary import boundary_after
        self.assertEqual(boundary_after('他问：“你住在哪里？”'), "terminal_punctuation")
        self.assertEqual(boundary_after('他问（你住在哪里）'), "chinese_question_ending")
        self.assertEqual(boundary_after('"你在哪"'), "chinese_question_ending")
        self.assertEqual(boundary_after("Bạn đi được không】"), "vietnamese_question_ending")
        self.assertIsNone(boundary_after("được không thôi"))
        self.assertIsNone(boundary_after("tại sao mà"))

    def test_dub_grouping_preserves_order_and_boundary_reason_without_text(self):
        optimizer_path = SKILL_DIR / "viet_dub_timing_optimizer.py"
        spec = importlib.util.spec_from_file_location("optimizer_boundary_test", optimizer_path)
        optimizer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(optimizer)
        entries = [
            {"id": 7, "start_ms": 0, "end_ms": 400, "source_text": "你去哪？"},
            {"id": 8, "start_ms": 400, "end_ms": 800, "source_text": "去学校"},
            {"id": 9, "start_ms": 800, "end_ms": 1100, "source_text": "然后"},
            {"id": 10, "start_ms": 1100, "end_ms": 1500, "source_text": "我们走"},
        ]
        original_floor = optimizer.CONFIG["dub_short_group_min_ratio"]
        optimizer.CONFIG["dub_short_group_min_ratio"] = 0
        try:
            groups, report = optimizer.group_entries_for_dub(entries, with_report=True)
        finally:
            optimizer.CONFIG["dub_short_group_min_ratio"] = original_floor
        self.assertEqual([[cue["id"] for cue in group] for group in groups], [[7], [8, 9, 10]])
        self.assertEqual(report[0], {"source_cue_ids": [7], "boundary_reason": "terminal_punctuation"})
        self.assertNotIn("source_text", repr(report))

    def test_dub_floor_is_unchanged_for_nonterminal_short_fragments(self):
        optimizer_path = SKILL_DIR / "viet_dub_timing_optimizer.py"
        spec = importlib.util.spec_from_file_location("optimizer_floor_test", optimizer_path)
        optimizer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(optimizer)
        entries = [
            {"id": 1, "start_ms": 0, "end_ms": 400, "source_text": "một"},
            {"id": 2, "start_ms": 400, "end_ms": 800, "source_text": "hai"},
        ]
        original_floor = optimizer.CONFIG["dub_short_group_min_ratio"]
        optimizer.CONFIG["dub_short_group_min_ratio"] = 0
        try:
            groups = optimizer.group_entries_for_dub(entries)
        finally:
            optimizer.CONFIG["dub_short_group_min_ratio"] = original_floor
        self.assertEqual([[cue["id"] for cue in group] for group in groups], [[1, 2]])

    def test_resona_grouping_uses_the_shared_boundary_policy(self):
        run_sh = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
        self.assertIn("from dialogue_boundary import boundary_after", run_sh)
        self.assertIn("resona_hard_boundary", run_sh)

    def test_resona_grouping_preserves_original_source_ids_and_group_index(self):
        from resona_grouping import group_resona_entries
        entries = [
            (0, 200, "xin"),
            (200, 400, "chào"),
            (400, 900, "bạn"),
        ]
        grouped, metadata = group_resona_entries(
            entries, [41, 77, 103], min_chars=12, max_chars=100,
            max_cues=3, hard_max_duration_ms=2000, max_internal_gap_ms=0,
        )
        self.assertEqual(grouped, [(0, 900, "xin. chào. bạn.")])
        self.assertEqual(metadata[1]["source_cue_ids"], [41, 77, 103])
        self.assertEqual(metadata[1]["group_index"], 1)

    def test_identical_timestamps_keep_distinct_ordered_source_ids(self):
        """Ordinal identity must survive grouping; timestamps are not unique cue keys."""
        from resona_grouping import group_resona_entries
        entries = [
            (0, 400, "xin", 1),
            (0, 400, "chào", 2),
            (400, 900, "bạn", 3),
        ]
        grouped, metadata = group_resona_entries(
            entries, min_chars=12, max_chars=100, max_cues=3,
            hard_max_duration_ms=2000, max_internal_gap_ms=0,
        )
        self.assertEqual(grouped, [(0, 900, "xin. chào. bạn.")])
        self.assertEqual(metadata[1]["source_cue_ids"], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
