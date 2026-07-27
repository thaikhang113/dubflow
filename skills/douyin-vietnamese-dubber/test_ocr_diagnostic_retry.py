#!/usr/bin/env python3
import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parent / "ocr_subtitle_transcript.py"
SPEC = importlib.util.spec_from_file_location("ocr_diagnostic_retry_test", SCRIPT)
OCR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OCR)


class OcrDiagnosticRetryTests(unittest.TestCase):
    def test_zero_samples_retry_uses_wider_roi_without_prefilter(self):
        frames = [Path(f"frame-{index:03d}.jpg") for index in range(30)]
        args = SimpleNamespace(
            start=0.0,
            fps=1.0,
            roi_top=0.58,
            roi_bottom=1.0,
            prefilter_min_ratio=0.0012,
            prefilter_min_pixels=80,
            vision_min_confidence=0.45,
            vision_timeout=5.0,
        )
        sample = [{"time": 15.0, "text": "中文字幕", "confidence": 0.9, "bbox": None}]
        with patch.object(OCR, "run_vision_on_frames", return_value=(sample, [], 0, {"vision_calls": 1})) as run:
            result = OCR.run_zero_sample_diagnostic_retry(frames, args, None)
        retry_args = run.call_args.args[1]
        self.assertEqual(result["samples"], sample)
        self.assertLessEqual(len(run.call_args.args[0]), 12)
        self.assertEqual(retry_args.roi_top, 0.35)
        self.assertEqual(retry_args.prefilter_min_ratio, 0.0)
        self.assertEqual(retry_args.prefilter_min_pixels, 0)
        self.assertEqual(result["classification"], "subtitle_detected_on_retry")

    def test_no_subtitle_reasons_are_not_reported_as_subsystem_failure(self):
        self.assertEqual(
            OCR.classify_zero_sample_result({"no_subtitle": 8, "no_cjk": 2}, [], False),
            "no_visible_subtitles",
        )
        self.assertEqual(
            OCR.classify_zero_sample_result({"vision_error": 8}, [{"error": "boom"}], False),
            "ocr_subsystem_failed",
        )

    def test_budget_expiry_is_returned_as_timeout(self):
        frames = [Path("frame-000.jpg")]
        args = SimpleNamespace(
            start=0.0, fps=1.0, roi_top=0.58, roi_bottom=1.0,
            prefilter_min_ratio=0.0012, prefilter_min_pixels=80,
            vision_min_confidence=0.45, vision_timeout=5.0,
        )
        with patch.object(OCR, "run_vision_on_frames", return_value=([], [], 0, {"budget_expired": 1})):
            with patch.object(OCR, "_budget_expired", return_value=True):
                result = OCR.run_zero_sample_diagnostic_retry(frames, args, None)
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["classification"], "timeout")


if __name__ == "__main__":
    unittest.main(verbosity=2)
