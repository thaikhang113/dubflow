"""Kiểm thử việc trích dạng sóng từ tệp âm thanh."""
from __future__ import annotations

import json
import math
import os
import wave

import numpy as np
import pytest

from autodub_gui import waveform
from autodub_gui.waveform import CACHE_NAME, DEFAULT_BUCKETS, peaks


def _write_wav(path, seconds=1.0, rate=8000, channels=1, width=2,
               amplitude=0.5, silent_tail=0.0):
    """Ghi một tệp WAV dạng PCM để kiểm thử."""
    frames = int(rate * seconds)
    time = np.arange(frames) / rate
    signal = np.sin(2 * math.pi * 440 * time) * amplitude
    if silent_tail > 0:
        quiet_from = int(frames * (1 - silent_tail))
        signal[quiet_from:] = 0.0
    scale = np.iinfo(np.int16 if width == 2 else np.int32).max
    data = (signal * scale).astype(np.int16 if width == 2 else np.int32)
    if channels > 1:
        data = np.repeat(data[:, None], channels, axis=1).ravel()
    with wave.open(str(path), "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(width)
        out.setframerate(rate)
        out.writeframes(data.tobytes())
    return str(path)


# -- Trường hợp bình thường --------------------------------------------

def test_returns_requested_number_of_buckets(tmp_path) -> None:
    path = _write_wav(tmp_path / "am.wav")
    assert len(peaks(path, buckets=100)) == 100


def test_values_are_within_zero_and_one(tmp_path) -> None:
    path = _write_wav(tmp_path / "am.wav")
    assert all(0.0 <= v <= 1.0 for v in peaks(path, buckets=200))


def test_louder_audio_gives_higher_peaks(tmp_path) -> None:
    quiet = peaks(_write_wav(tmp_path / "nho.wav", amplitude=0.2), buckets=50)
    loud = peaks(_write_wav(tmp_path / "to.wav", amplitude=0.9), buckets=50)
    assert max(loud) > max(quiet)


def test_silence_shows_as_near_zero(tmp_path) -> None:
    """Nửa cuối im lặng phải cho biên độ gần bằng không."""
    path = _write_wav(tmp_path / "im.wav", silent_tail=0.5)
    values = peaks(path, buckets=100)
    assert max(values[:40]) > 0.1
    assert max(values[60:]) < 0.01


def test_stereo_is_supported(tmp_path) -> None:
    path = _write_wav(tmp_path / "hai_kenh.wav", channels=2)
    assert len(peaks(path, buckets=64)) == 64


def test_thirty_two_bit_is_supported(tmp_path) -> None:
    path = _write_wav(tmp_path / "ba_hai_bit.wav", width=4)
    values = peaks(path, buckets=64)
    assert len(values) == 64
    assert max(values) > 0.1


def test_default_bucket_count_is_reasonable() -> None:
    assert DEFAULT_BUCKETS >= 1000


# -- Trường hợp hỏng ---------------------------------------------------

def test_missing_file_returns_empty() -> None:
    assert peaks("khong_ton_tai.wav") == []


def test_empty_path_returns_empty() -> None:
    assert peaks("") == []


def test_non_wav_file_returns_empty(tmp_path) -> None:
    """Tệp không phải WAV thì trả về rỗng chứ không được vẽ sóng giả."""
    path = tmp_path / "gia.wav"
    path.write_bytes(b"day khong phai tep wav")
    assert peaks(str(path)) == []


def test_unsupported_sample_width_returns_empty(tmp_path) -> None:
    """WAV 8 bit không nằm trong định dạng lõi xử lý sinh ra."""
    path = tmp_path / "tam_bit.wav"
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(1)
        out.setframerate(8000)
        out.writeframes(b"\x80" * 8000)
    assert peaks(str(path)) == []


def test_zero_buckets_returns_empty(tmp_path) -> None:
    path = _write_wav(tmp_path / "am.wav")
    assert peaks(path, buckets=0) == []


# -- Bộ nhớ đệm --------------------------------------------------------

def test_cache_file_is_written(tmp_path) -> None:
    path = _write_wav(tmp_path / "am.wav")
    peaks(path, buckets=64)
    assert (tmp_path / CACHE_NAME).is_file()


def test_cache_is_reused_on_second_call(tmp_path) -> None:
    """Lần gọi thứ hai đọc từ bộ nhớ đệm chứ không quét lại tệp."""
    path = _write_wav(tmp_path / "am.wav")
    first = peaks(path, buckets=64)
    # Ghi đè bộ nhớ đệm bằng giá trị nhận ra được để chứng minh nó được dùng.
    marker = [0.5] * 64
    with open(tmp_path / CACHE_NAME, encoding="utf-8") as f:
        data = json.load(f)
    data["peaks"] = marker
    with open(tmp_path / CACHE_NAME, "w", encoding="utf-8") as f:
        json.dump(data, f)
    assert peaks(path, buckets=64) == marker
    assert first != marker


def test_cache_ignored_when_bucket_count_changes(tmp_path) -> None:
    path = _write_wav(tmp_path / "am.wav")
    peaks(path, buckets=64)
    assert len(peaks(path, buckets=128)) == 128


def test_cache_ignored_when_audio_changes(tmp_path) -> None:
    path = _write_wav(tmp_path / "am.wav", amplitude=0.2)
    quiet = peaks(path, buckets=64)
    _write_wav(tmp_path / "am.wav", amplitude=0.9)
    os.utime(path, (2_000_000, 2_000_000))
    assert max(peaks(path, buckets=64)) > max(quiet)


def test_corrupted_cache_is_ignored(tmp_path) -> None:
    path = _write_wav(tmp_path / "am.wav")
    (tmp_path / CACHE_NAME).write_text("{ hỏng", encoding="utf-8")
    assert len(peaks(path, buckets=64)) == 64


def test_cache_can_be_disabled(tmp_path) -> None:
    path = _write_wav(tmp_path / "am.wav")
    peaks(path, buckets=64, use_cache=False)
    assert not (tmp_path / CACHE_NAME).exists()


def test_clear_cache_removes_file(tmp_path) -> None:
    work = tmp_path / "du_an_vi"
    data = work / "data"
    data.mkdir(parents=True)
    path = _write_wav(data / "audio_vi_full.wav")
    peaks(path, buckets=32)
    assert waveform.clear_cache(str(work)) is True
    assert not (data / CACHE_NAME).exists()


def test_clear_cache_on_missing_file_is_safe(tmp_path) -> None:
    assert waveform.clear_cache(str(tmp_path)) is False


# -- Chọn nguồn âm thanh -----------------------------------------------

def test_prefers_vietnamese_audio(tmp_path) -> None:
    """Ưu tiên giọng Việt vì đó là thứ người dùng cần canh."""
    work = tmp_path / "du_an_vi"
    data = work / "data"
    data.mkdir(parents=True)
    _write_wav(data / "original_audio.wav")
    _write_wav(data / "audio_vi_full.wav")
    assert waveform.source_for(str(work)).endswith("audio_vi_full.wav")


def test_falls_back_to_original_audio(tmp_path) -> None:
    work = tmp_path / "du_an_vi"
    data = work / "data"
    data.mkdir(parents=True)
    _write_wav(data / "original_audio.wav")
    assert waveform.source_for(str(work)).endswith("original_audio.wav")


def test_no_audio_returns_empty_source(tmp_path) -> None:
    work = tmp_path / "du_an_vi"
    (work / "data").mkdir(parents=True)
    assert waveform.source_for(str(work)) == ""
