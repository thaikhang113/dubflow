"""Work-dir layout — where each artifact of a dub run lives.

Layout (new runs)::

    <work_dir>/
    ├── dubbed_video.mp4       ← video kết quả (người dùng cần)
    ├── transcript_vi.srt      ← phụ đề tiếng Việt (đăng kèm nếu muốn)
    ├── youtube/               ← tiêu đề, mô tả, hashtag, thumbnail
    └── data/                  ← file kỹ thuật cho resume/chỉnh sửa
        ├── original_audio.wav, vocals.wav, no_vocals.wav
        ├── transcript_original.json/.srt, transcript_vi.json
        ├── audio_vi_full.wav, slowed_video.mp4, slowed_background.wav
        ├── report.json, timing_guide.json, render_opts.json
        └── segments/, segments_speed*/

Older work dirs kept everything flat in the root. ``is_legacy_layout()``
detects them and every helper falls back to the flat path, so resume and the
segment editor keep working on dirs produced by previous builds.
"""
from __future__ import annotations

import os

DATA_SUBDIR = "data"
YOUTUBE_SUBDIR = "youtube"

# Any of these at the work-dir ROOT ⇒ dir was produced by an older build.
_LEGACY_MARKERS = ("transcript_original.json", "transcript_vi.json",
                   "original_audio.wav", "segments")


def is_legacy_layout(work_dir: str) -> bool:
    """True when this work dir keeps technical files flat in the root."""
    return any(os.path.exists(os.path.join(work_dir, m))
               for m in _LEGACY_MARKERS)


def data_dir(work_dir: str, create: bool = False) -> str:
    """Directory holding technical/pipeline artifacts."""
    if is_legacy_layout(work_dir):
        return work_dir
    d = os.path.join(work_dir, DATA_SUBDIR)
    if create:
        os.makedirs(d, exist_ok=True)
    return d


def data_path(work_dir: str, *names: str, create_dir: bool = False) -> str:
    """Path of a technical artifact (transcripts, wavs, caches, reports)."""
    return os.path.join(data_dir(work_dir, create=create_dir), *names)


def load_video_meta(work_dir: str) -> dict:
    """Title/uploader của video nguồn (``data/video_meta.json``).

    Downloader ghi file này lúc tải; trả về ``{}`` khi chưa có hoặc hỏng —
    title chỉ là ngữ cảnh bổ sung, thiếu không được làm hỏng bước nào.
    """
    import json
    try:
        with open(data_path(work_dir, "video_meta.json"),
                  encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def youtube_dir(work_dir: str, create: bool = False) -> str:
    """Directory holding YouTube metadata + thumbnails (user-facing)."""
    if is_legacy_layout(work_dir):
        return work_dir
    d = os.path.join(work_dir, YOUTUBE_SUBDIR)
    if create:
        os.makedirs(d, exist_ok=True)
    return d
