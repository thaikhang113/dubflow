"""Trích dạng sóng từ tệp âm thanh để vẽ trên dải thời gian.

Đọc bằng thư viện chuẩn `wave` cộng với numpy, theo từng khối 1 MB, nên tệp
dài mấy chục phút cũng không nạp hết vào bộ nhớ. Kết quả được ghi đệm cạnh
tệp âm thanh, lần mở sau không phải tính lại.

Chỉ hỗ trợ tệp WAV dạng PCM 16 hoặc 32 bit — đúng loại mà lõi xử lý sinh ra.
Định dạng khác trả về danh sách rỗng và giao diện sẽ hiện một dải phẳng mờ
kèm chú giải. Tuyệt đối không vẽ dạng sóng giả.
"""
from __future__ import annotations

import json
import os
import wave

import numpy as np

CACHE_NAME = "waveform_peaks.json"
DEFAULT_BUCKETS = 4000

_CHUNK_BYTES = 1024 * 1024        # đọc mỗi lần 1 MB
_SUPPORTED_WIDTHS = {2: np.int16, 4: np.int32}
_CACHE_VERSION = 1

# Thứ tự ưu tiên nguồn âm thanh: giọng Việt trước, vì đó là thứ người dùng canh
_PREFERRED_SOURCES = ("audio_vi_full.wav", "original_audio.wav")


def source_for(work_dir: str) -> str:
    """Tệp âm thanh nên vẽ dạng sóng cho một thư mục dự án."""
    from autodub.workdir import data_path

    for name in _PREFERRED_SOURCES:
        path = data_path(work_dir, name)
        if os.path.isfile(path):
            return path
    return ""


# Các track của dải thời gian nhiều lớp: (loại, các tên tệp theo thứ tự ưu tiên)
# Nhạc nền: ưu tiên slowed_background.wav vì nó đã theo nhịp video cuối
# (khi có làm chậm); no_vocals.wav ở tốc độ gốc chỉ là phương án dự phòng.
_TRACK_SOURCES = (
    ("original", ("original_audio.wav",)),
    ("voice", ("audio_vi_full.wav",)),
    ("music", ("slowed_background.wav", "no_vocals.wav")),
)


def track_sources(work_dir: str) -> dict[str, str]:
    """Đường dẫn âm thanh cho từng track đang có mặt trong dự án.

    Chỉ trả về track mà tệp thật sự tồn tại — track thiếu sẽ bị ẩn
    trên dải thời gian thay vì vẽ dải phẳng giả.
    """
    from autodub.workdir import data_path

    found: dict[str, str] = {}
    for kind, names in _TRACK_SOURCES:
        for name in names:
            path = data_path(work_dir, name)
            if os.path.isfile(path):
                found[kind] = path
                break
    return found


def cache_name_for(wav_path: str) -> str:
    """Tên tệp đệm riêng cho từng nguồn âm thanh.

    Chỉ `audio_vi_full.wav` (nguồn chính, trùng với dải đơn cũ) giữ tên
    `waveform_peaks.json` để tận dụng đệm sẵn có; mọi nguồn khác dùng tên
    theo gốc tệp — hai track không bao giờ ghi đè đệm của nhau.
    """
    base = os.path.basename(wav_path)
    if base == "audio_vi_full.wav":
        return CACHE_NAME
    stem = os.path.splitext(base)[0]
    return f"waveform_peaks_{stem}.json"


def _cache_path(wav_path: str, cache_name: str | None = None) -> str:
    return os.path.join(os.path.dirname(wav_path), cache_name or CACHE_NAME)


def _read_cache(wav_path: str, buckets: int,
                cache_name: str | None = None) -> list[float] | None:
    """Đọc bộ nhớ đệm nếu nó còn khớp với tệp âm thanh hiện tại."""
    path = _cache_path(wav_path, cache_name)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if (data.get("version") != _CACHE_VERSION
                or data.get("src") != os.path.basename(wav_path)
                or data.get("n") != buckets
                or abs(float(data.get("mtime", 0))
                       - os.path.getmtime(wav_path)) > 1e-6):
            return None
        peaks = data.get("peaks")
        return [float(v) for v in peaks] if isinstance(peaks, list) else None
    except (OSError, ValueError, TypeError):
        return None


def _write_cache(wav_path: str, buckets: int, peaks: list[float],
                 cache_name: str | None = None) -> None:
    """Ghi bộ nhớ đệm; hỏng thì bỏ qua vì đây chỉ là thứ giúp chạy nhanh hơn."""
    try:
        with open(_cache_path(wav_path, cache_name), "w",
                  encoding="utf-8") as f:
            json.dump({
                "version": _CACHE_VERSION,
                "src": os.path.basename(wav_path),
                "mtime": os.path.getmtime(wav_path),
                "n": buckets,
                "peaks": [round(v, 4) for v in peaks],
            }, f)
    except OSError:
        pass


def peaks(wav_path: str, buckets: int = DEFAULT_BUCKETS,
          use_cache: bool = True, cache_name: str | None = None) -> list[float]:
    """Biên độ lớn nhất của từng đoạn, quy về khoảng từ 0 tới 1.

    Trả về danh sách rỗng khi tệp không đọc được hoặc không phải WAV dạng
    PCM 16 hay 32 bit.
    """
    if buckets <= 0 or not wav_path or not os.path.isfile(wav_path):
        return []
    if use_cache:
        cached = _read_cache(wav_path, buckets, cache_name)
        if cached is not None:
            return cached
    result = _compute_peaks(wav_path, buckets)
    if result and use_cache:
        _write_cache(wav_path, buckets, result, cache_name)
    return result


def _compute_peaks(wav_path: str, buckets: int) -> list[float]:
    """Quét cả tệp một lượt, gom biên độ lớn nhất của từng đoạn."""
    try:
        with wave.open(wav_path, "rb") as source:
            width = source.getsampwidth()
            channels = max(1, source.getnchannels())
            frames = source.getnframes()
            dtype = _SUPPORTED_WIDTHS.get(width)
            if dtype is None or frames <= 0:
                return []
            return _scan(source, dtype, width, channels, frames, buckets)
    except (wave.Error, OSError, EOFError, ValueError):
        return []


def _scan(source, dtype, width: int, channels: int,
          frames: int, buckets: int) -> list[float]:
    """Đọc theo khối và dồn vào các ô, không nạp cả tệp vào bộ nhớ."""
    totals = np.zeros(buckets, dtype=np.float64)
    frames_per_chunk = max(1, _CHUNK_BYTES // (width * channels))
    full_scale = float(np.iinfo(dtype).max)
    position = 0

    while position < frames:
        raw = source.readframes(min(frames_per_chunk, frames - position))
        if not raw:
            break
        samples = np.frombuffer(raw, dtype=dtype)
        if channels > 1:
            usable = (len(samples) // channels) * channels
            samples = samples[:usable].reshape(-1, channels).mean(axis=1)
        read_frames = len(samples)
        if read_frames == 0:
            break
        amplitude = np.abs(samples.astype(np.float64))
        # Mỗi mẫu thuộc về ô nào trên trục thời gian
        indices = ((np.arange(position, position + read_frames)
                    * buckets) // frames).astype(np.int64)
        np.maximum.at(totals, indices, amplitude)
        position += read_frames

    if full_scale <= 0:
        return []
    normalized = np.clip(totals / full_scale, 0.0, 1.0)
    return [float(v) for v in normalized]


def clear_cache(work_dir: str) -> bool:
    """Xóa bộ nhớ đệm dạng sóng của một dự án — gồm cả các track phụ."""
    from autodub.workdir import data_path

    folder = os.path.dirname(data_path(work_dir, CACHE_NAME))
    removed = False
    try:
        names = os.listdir(folder)
    except OSError:
        return False
    for name in names:
        if name.startswith("waveform_peaks") and name.endswith(".json"):
            try:
                os.remove(os.path.join(folder, name))
                removed = True
            except OSError:
                continue
    return removed
