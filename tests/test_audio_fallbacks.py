"""Fallback của ffmpeg trên từng câu phải được ĐẾM, không nuốt im lặng.

Giữ clip sai tốc độ thay vì bỏ clip là cố ý (thiếu clip → video câm đoạn đó).
Nhưng người dùng nghe thấy chất lượng tệ mà không có dòng nào giải thích thì
không sửa được gì — nên mỗi lần rơi vào nhánh dự phòng phải vào sổ.
"""
import os
import threading
from unittest import mock

import pytest
from pydub.generators import Sine

from autodub.media import audio


@pytest.fixture(autouse=True)
def clean_ledger():
    audio.FALLBACKS.reset()
    yield
    audio.FALLBACKS.reset()


def _make_wav(path: str, duration_ms: int = 500):
    Sine(440).to_audio_segment(duration=duration_ms).export(path, format="wav")


def test_apply_atempo_failure_copies_source_and_counts(tmp_path):
    src = str(tmp_path / "seg_00007.wav")
    dst = str(tmp_path / "out" / "seg_00007.wav")
    os.makedirs(os.path.dirname(dst))
    _make_wav(src)

    with mock.patch("autodub.media.audio.subprocess.run",
                    return_value=mock.Mock(returncode=1, stderr="boom")):
        assert audio.apply_atempo(src, dst, 1.2) is False

    # Clip vẫn phải tồn tại — thiếu file là mất tiếng cả câu.
    assert os.path.exists(dst)
    assert os.path.getsize(dst) == os.path.getsize(src)
    assert audio.FALLBACKS.snapshot()["atempo_failed"] == [7]


def test_apply_atempo_success_records_nothing(tmp_path):
    src = str(tmp_path / "seg_00001.wav")
    dst = str(tmp_path / "seg_00001.out.wav")
    _make_wav(src)

    def fake_run(cmd, **kwargs):
        _make_wav(cmd[-1])
        return mock.Mock(returncode=0, stderr="")

    with mock.patch("autodub.media.audio.subprocess.run", side_effect=fake_run):
        assert audio.apply_atempo(src, dst, 1.1) is True
    assert audio.FALLBACKS.snapshot() == {}


def test_atempo_timeout_is_counted_too(tmp_path):
    import subprocess

    src = str(tmp_path / "seg_00003.wav")
    dst = str(tmp_path / "out3.wav")
    _make_wav(src)

    with mock.patch("autodub.media.audio.subprocess.run",
                    side_effect=subprocess.TimeoutExpired("ffmpeg", 120)):
        assert audio.apply_atempo(src, dst, 1.5) is False
    assert audio.FALLBACKS.snapshot()["atempo_failed"] == [3]


def test_postprocess_failure_keeps_raw_clip_and_counts(tmp_path):
    src = str(tmp_path / "seg_00042.wav")
    dst = str(tmp_path / "post" / "seg_00042.wav")
    os.makedirs(os.path.dirname(dst))
    _make_wav(src, duration_ms=800)

    with mock.patch("autodub.media.audio.subprocess.run",
                    return_value=mock.Mock(returncode=1, stderr="boom")):
        assert audio.postprocess_voice_clip(src, dst) is False

    assert os.path.exists(dst)
    assert audio.FALLBACKS.snapshot()["postprocess_failed"] == [42]


def test_slow_segments_failure_counts_by_segment_id(tmp_path):
    src_dir = str(tmp_path / "src")
    dst_dir = str(tmp_path / "dst")
    os.makedirs(src_dir)
    _make_wav(os.path.join(src_dir, "seg_00011.wav"))

    with mock.patch("autodub.media.audio.subprocess.run",
                    return_value=mock.Mock(returncode=1, stderr="boom")):
        audio.slow_segments([{"id": 11}], src_dir, dst_dir, 0.9)

    assert os.path.exists(os.path.join(dst_dir, "seg_00011.wav"))
    assert audio.FALLBACKS.snapshot()["atempo_failed"] == [11]


def test_ledger_is_thread_safe():
    """Các pool ffmpeg ghi song song — mất mục nào là báo cáo sai."""
    def worker(base: int):
        for i in range(50):
            audio.FALLBACKS.add("atempo_failed", base + i)

    threads = [threading.Thread(target=worker, args=(t * 100,))
               for t in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(audio.FALLBACKS.snapshot()["atempo_failed"]) == 400


def test_reset_clears_between_videos():
    audio.FALLBACKS.add("atempo_failed", 1)
    audio.FALLBACKS.reset()
    assert audio.FALLBACKS.snapshot() == {}


def test_snapshot_is_a_copy():
    """Người đọc sổ không được sửa được sổ."""
    audio.FALLBACKS.add("atempo_failed", 5)
    snap = audio.FALLBACKS.snapshot()
    snap["atempo_failed"].append(999)
    assert audio.FALLBACKS.snapshot()["atempo_failed"] == [5]
