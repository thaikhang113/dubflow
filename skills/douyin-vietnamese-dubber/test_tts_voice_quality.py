#!/usr/bin/env python3
import importlib.util
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("tts_voice_quality", SKILL_DIR / "tts_voice_quality.py")
quality = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quality)


def test_normalize_spoken_text():
    text = quality.normalize_spoken_text("  Xin\u0000 chào，  Việt Nam！ ")
    assert text == "Xin chào, Việt Nam!"


def test_text_gate_rejects_non_vietnamese_and_repetition():
    assert "contains_cjk" in quality.text_quality_issues("你好")
    assert "mojibake" in quality.text_quality_issues("Xin chÃ o")
    assert "repeated_short_token" in quality.text_quality_issues("mo mo mo mo")
    assert quality.text_quality_issues("Mặc nhiên, anh ta quay trở lại.") == []


def test_voice_comparison_marks_repeated_audio_critical():
    expected = [{"index": 1, "start": 0.0, "end": 2.0, "text": "Mặc nhiên anh ta quay lại"}]
    observed = [{"start": 0.0, "end": 2.0, "text": "mo mo mo mo"}]
    report = quality.compare_transcripts(expected, observed)
    assert report["status"] == "fail"
    assert report["critical_cue_ids"] == [1]
    assert "repeated_short_token" in report["cues"][0]["reasons"]


def test_voice_comparison_keeps_low_similarity_as_warning():
    expected = [{"index": 1, "start": 0.0, "end": 2.0, "text": "Anh ta quay trở lại"}]
    observed = [{"start": 0.0, "end": 2.0, "text": "Người đó đã về"}]
    report = quality.compare_transcripts(expected, observed)
    assert report["status"] == "warning"
    assert report["critical_cue_ids"] == []


def test_retry_overrides_only_include_critical_cues():
    report = {
        "critical_cue_ids": [2],
        "cues": [
            {"cue_id": 1, "expected": "Câu đầu", "level": "ok"},
            {"cue_id": 2, "expected": "Mặc nhiên anh ta quay lại", "level": "critical"},
        ],
    }
    assert quality.build_retry_overrides(report) == {"2": "Mặc nhiên anh ta quay lại."}


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    for test in tests:
        test()
    print(f"tts voice quality tests passed: {len(tests)}")
