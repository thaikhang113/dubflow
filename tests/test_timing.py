"""Tests for the soft timing fit (autodub.media.timing).

Ràng buộc thiết kế số 1: KHÔNG câu nhanh câu chậm — dồn trễ vào khoảng lặng
trước, nén atempo chỉ khi bất khả kháng và có trần thấp.
"""
import math
import os
import struct
import wave

import pytest

from autodub.config import Settings
from autodub.media.timing import apply_soft_timing, plan_placements


def _segs(*starts):
    return [{"id": i + 1, "start": float(s)} for i, s in enumerate(starts)]


def test_no_intervention_when_everything_fits():
    p, r = plan_placements(_segs(0, 5, 10), [4.0, 4.0, 4.0])
    assert [x["start"] for x in p] == [0.0, 5.0, 10.0]
    assert all(x["atempo"] == 1.0 for x in p)
    assert r.segments_shifted == 0
    assert r.segments_overlapped == 0


def test_overflow_shifts_next_segment_not_speed():
    # Câu 1 dài 4s nhưng câu 2 bắt đầu ở 3s → câu 2 dồn trễ, KHÔNG nén.
    p, r = plan_placements(_segs(0, 3, 10), [4.0, 3.0, 2.0])
    assert p[1]["start"] > 4.0            # dồn sau khi câu 1 nói xong + gap
    assert p[1]["atempo"] == 1.0          # tốc độ đọc không đổi
    assert p[2]["start"] == 10.0          # drift tan ở khoảng lặng
    assert r.segments_overlapped == 0


def test_drift_capped_and_compression_bounded():
    # 5 câu, mỗi câu 3.5s trong slot 2s — drift phải kịch trần rồi dừng,
    # atempo không bao giờ vượt trần.
    segs = _segs(2, 4, 6, 8, 10)
    p, r = plan_placements(segs, [3.5] * 5, max_drift_s=1.5, max_atempo=1.1)
    for seg, placed in zip(segs, p):
        assert placed["start"] - seg["start"] <= 1.5 + 1e-9
        assert placed["atempo"] <= 1.1 + 1e-9
    # Quá tải thật sự thì phải GHI NHẬN chồng lấn (không giấu).
    assert r.segments_overlapped > 0
    assert r.total_overlap_s > 0


def test_missing_duration_keeps_natural_start():
    p, _ = plan_placements(_segs(0, 2), [None, 3.0])
    assert p[0]["start"] == 0.0
    assert p[1]["start"] == 2.0


def test_min_gap_respected():
    p, _ = plan_placements(_segs(0, 4), [4.0, 2.0], min_gap_s=0.2)
    assert p[1]["start"] == pytest.approx(4.2, abs=1e-6)


def _write_tone(path, dur, rate=24000):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        n = int(dur * rate)
        w.writeframes(struct.pack(
            f"<{n}h",
            *[int(8000 * math.sin(2 * math.pi * 440 * i / rate))
              for i in range(n)]))


def test_apply_soft_timing_mutates_timeline(tmp_path):
    seg_dir = tmp_path / "segs"
    seg_dir.mkdir()
    _write_tone(str(seg_dir / "seg_00001.wav"), 4.0)
    _write_tone(str(seg_dir / "seg_00002.wav"), 2.0)
    segments = [
        {"id": 1, "start": 0.0, "end": 3.0, "duration": 3.0},
        {"id": 2, "start": 3.0, "end": 5.0, "duration": 2.0},
    ]
    settings = Settings()
    out_dir, report = apply_soft_timing(
        segments, str(seg_dir), str(tmp_path / "timed"), settings)
    # Không câu nào bị nén → dùng thẳng thư mục nguồn, không copy.
    assert out_dir == str(seg_dir)
    assert segments[1]["start"] >= 4.1
    # end đi theo vị trí đặt + thời lượng clip thật.
    assert segments[1]["end"] == pytest.approx(segments[1]["start"] + 2.0,
                                               abs=0.05)
    # duration giữ nguyên giá trị GỐC cho báo cáo.
    assert segments[0]["duration"] == 3.0
    assert report.segments_shifted == 1
    assert report.segments_overlapped == 0
