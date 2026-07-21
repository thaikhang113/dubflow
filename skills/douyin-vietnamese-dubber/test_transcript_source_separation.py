#!/usr/bin/env python3
"""Regression coverage for keeping ASR and OCR transcripts separate."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent
SELECTOR = SKILL_DIR / "choose_transcript_source.py"
REPAIR = SKILL_DIR / "asr_timing_repair.py"
RUN_SH = SKILL_DIR / "run.sh"


def srt(cues):
    lines = []
    for number, (start, end, text) in enumerate(cues, 1):
        lines.extend((str(number), f"00:00:{start:02d},000 --> 00:00:{end:02d},000", text, ""))
    return "\n".join(lines).rstrip() + "\n"


def write_selector_inputs(directory, asr_text, ocr_text, *, asr_severe=False, video_duration=400):
    asr = directory / "original_asr.srt"
    ocr = directory / "original_ocr.srt"
    output = directory / "selected_transcript.srt"
    asr_report = directory / "asr.json"
    ocr_report = directory / "ocr.json"
    decision = directory / "decision.json"
    consistency = directory / "consistency.json"
    asr.write_text(asr_text, encoding="utf-8")
    ocr.write_text(ocr_text, encoding="utf-8")
    asr_report.write_text(json.dumps({"video_duration": video_duration, "hallucination": {"severe": asr_severe}}), encoding="utf-8")
    ocr_report.write_text(json.dumps({"video_duration": video_duration, "coverage_ratio": 0.8, "avg_confidence": 0.95, "quality_ok": True}), encoding="utf-8")
    return asr, ocr, output, asr_report, ocr_report, decision, consistency


def select(paths):
    asr, ocr, output, asr_report, ocr_report, decision, consistency = paths
    return subprocess.run([
        sys.executable, str(SELECTOR), "--mode", "auto", "--asr-srt", str(asr),
        "--ocr-srt", str(ocr), "--output-srt", str(output), "--asr-report", str(asr_report),
        "--ocr-report", str(ocr_report), "--decision-json", str(decision),
        "--consistency-json", str(consistency),
    ], text=True, capture_output=True)


class TranscriptSourceSeparationTest(unittest.TestCase):
    def test_asr_primary_selected_bytes_equal_asr_and_sources_remain_distinct(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            asr_text = srt([(i * 2, i * 2 + 1, f"ASR speech {i}") for i in range(131)])
            ocr_text = srt([(i * 8, i * 8 + 2, f"OCR subtitle {i}") for i in range(45)])
            paths = write_selector_inputs(directory, asr_text, ocr_text)
            result = select(paths)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(paths[2].read_bytes(), paths[0].read_bytes())
            self.assertNotEqual(paths[0].read_bytes(), paths[1].read_bytes())
            decision = json.loads(paths[5].read_text(encoding="utf-8"))
            self.assertEqual(decision["chosen"], "asr")
            self.assertTrue(decision["ocr_extraction_quality_ok"])
            self.assertFalse(decision["ocr_transcript_usable"])
            self.assertTrue(decision["ocr_timing_anchor_usable"])

    def test_ocr_primary_selected_bytes_equal_ocr(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            asr_text = srt([(i * 2, i * 2 + 1, "loop") for i in range(20)])
            ocr_text = srt([(i * 4, i * 4 + 2, f"OCR subtitle {i}") for i in range(12)])
            paths = write_selector_inputs(directory, asr_text, ocr_text, asr_severe=True, video_duration=60)
            result = select(paths)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(paths[2].read_bytes(), paths[1].read_bytes())
            self.assertEqual(json.loads(paths[5].read_text(encoding="utf-8"))["chosen"], "ocr")

    def test_repeat_hallucination_never_builds_mixed_transcript(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            # A local 12-cue repeat run formerly triggered an ASR/OCR hybrid.
            asr_cues = [(i * 2, i * 2 + 1, "loop text" if 30 <= i < 42 else f"ASR {i}") for i in range(99)]
            ocr_cues = [(i * 8, i * 8 + 2, f"OCR {i}") for i in range(45)]
            paths = write_selector_inputs(directory, srt(asr_cues), srt(ocr_cues), video_duration=200)
            result = select(paths)
            self.assertEqual(result.returncode, 0, result.stderr)
            decision = json.loads(paths[5].read_text(encoding="utf-8"))
            self.assertEqual(decision["chosen"], "ocr")
            self.assertEqual(paths[2].read_bytes(), paths[1].read_bytes())
            self.assertFalse(decision["transcript_hybrid_used"])

    def test_ocr_anchor_repair_writes_diagnostic_without_overwriting_selected_text(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            selected = directory / "selected_transcript.srt"
            anchors = directory / "original_ocr.srt"
            diagnostic = directory / "selected_transcript.timing-repair.srt"
            report = directory / "repair.json"
            decision = directory / "decision.json"
            original = srt([(0, 10, "short")])
            selected.write_text(original, encoding="utf-8")
            anchors.write_text(srt([(1, 3, "anchor one"), (4, 6, "anchor two")]), encoding="utf-8")
            decision.write_text(json.dumps({"chosen": "asr", "severe_asr": False, "ocr_timing_anchor_usable": True, "asr_quality": {"long_thin_cues": 1}}), encoding="utf-8")
            result = subprocess.run([
                sys.executable, str(REPAIR), "--asr-srt", str(selected), "--ocr-srt", str(anchors),
                "--decision-json", str(decision), "--output-srt", str(diagnostic), "--report-json", str(report),
            ], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(selected.read_text(encoding="utf-8"), original)
            self.assertTrue(diagnostic.exists())
            self.assertNotEqual(diagnostic.read_text(encoding="utf-8"), original)

    def test_run_uses_immutable_sources_and_never_splits_ocr_selected_text_as_asr(self):
        script = RUN_SH.read_text(encoding="utf-8")
        self.assertIn('SELECTED_TRANSCRIPT_SRT="$OUT_DIR/selected_transcript.srt"', script)
        self.assertIn('--output-srt "$SELECTED_TRANSCRIPT_SRT"', script)
        self.assertIn('ORIGINAL_SRT="$SELECTED_TRANSCRIPT_SRT"', script)
        self.assertNotIn('split_long_asr_segments "$ORIGINAL_SRT"', script)
        self.assertIn('--asr-srt "$ORIGINAL_ASR_SRT"', script)
        self.assertIn('--output-srt "$TX_TIMING_REPAIR_SIDECAR_SRT"', script)
        tx_gate_block = script.split('if [[ "$tx_gate_status" -eq 7 ]]; then', 1)[1].split(
            'if load_manual_translation_if_available; then', 1
        )[0]
        self.assertIn('rm -f "$ORIGINAL_ASR_SPLIT_SRT"', tx_gate_block)
        self.assertNotIn('rm -f "$ORIGINAL_SRT"', tx_gate_block)
        self.assertLess(
            tx_gate_block.index('create_translate_pending "$tx_gate_msg"'),
            tx_gate_block.index('status_update "needs_attention"'),
        )


if __name__ == "__main__":
    unittest.main()
