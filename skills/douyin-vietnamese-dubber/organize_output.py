#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import unicodedata
from datetime import datetime
from pathlib import Path

FORBIDDEN = r'[/\\:*?"<>|]'

# Credential/session artifacts must never remain in job output or library copies.
FORBIDDEN_OUTPUT_BASENAMES = frozenset({
    "bilibili_cookies.txt",
    "cookies.txt",
    "cookies.netscape",
    ".env",
})


def scrub_forbidden_credentials(job_dir):
    """Remove known credential/session files from a job output directory.

    Returns list of basenames removed. Best-effort; never raises.
    """
    job_dir = Path(job_dir)
    removed = []
    for name in sorted(FORBIDDEN_OUTPUT_BASENAMES):
        path = job_dir / name
        if path.is_file():
            try:
                path.unlink()
                removed.append(name)
            except OSError:
                pass
    return removed


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return ""


def clean_name(value, fallback="Video Douyin"):
    value = re.sub(FORBIDDEN, " ", value or "")
    value = re.sub(r"[\r\n\t]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" ._-—")
    if not value:
        value = fallback
    if len(value) > 120:
        value = value[:120].rstrip(" ._-—")
    return value or fallback


def safe_slug(value):
    value = unicodedata.normalize("NFKD", value or "")
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return value or "video-douyin"


def srt_text_sample(path, limit=1200):
    content = read_text(path)
    content = re.sub(r"\d+\n\d\d:\d\d:\d\d,\d\d\d\s+-->\s+\d\d:\d\d:\d\d,\d\d\d", " ", content)
    content = re.sub(r"\d\d:\d\d:\d\d,\d\d\d\s+-->\s+\d\d:\d\d:\d\d,\d\d\d", " ", content)
    content = re.sub(r"\s+", " ", content).strip()
    return content[:limit]


def infer_title(job_dir):
    explicit = os.environ.get("FINAL_VIDEO_TITLE") or os.environ.get("MOVIE_TITLE") or os.environ.get("PHIM_TITLE")
    if explicit:
        return clean_name(explicit)
    thumb_title = clean_name(read_text(job_dir / "thumbnail_title.txt"), "")
    if thumb_title:
        title = re.sub(r"\b(tập|tap|ep|episode)\s*\d+\b.*$", "", thumb_title, flags=re.I).strip(" -–—:")
        title = re.sub(r"\b(từ|tu)\s*tập\s*\d+\s*(đến|-|to)\s*\d+\b.*$", "", title, flags=re.I).strip(" -–—:")
        if title and len(title) >= 3:
            return clean_name(title)
    sample = srt_text_sample(job_dir / "vietnamese.srt")
    quoted = re.findall(r"[“\"]([^”\"]{3,40})[”\"]", sample)
    if quoted:
        return clean_name(quoted[0])
    return ""


def infer_episode(job_dir):
    explicit = os.environ.get("FINAL_EPISODE_RANGE") or os.environ.get("EPISODE_RANGE") or os.environ.get("TAP_RANGE")
    if explicit:
        return normalize_episode(explicit)
    text = "\n".join([
        read_text(job_dir / "thumbnail_title.txt"),
        read_text(job_dir / "source_input.txt"),
        srt_text_sample(job_dir / "vietnamese.srt", 500),
    ])
    patterns = [
        r"(?:tập|tap|ep|episode)\s*(\d{1,3})\s*(?:-|đến|den|to)\s*(\d{1,3})",
        r"(?:từ|tu)\s*(?:tập|tap)\s*(\d{1,3})\s*(?:đến|den|-|to)\s*(\d{1,3})",
        r"(?:tập|tap|ep|episode)\s*(\d{1,3})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            if len(match.groups()) >= 2 and match.group(2):
                return f"{int(match.group(1)):02d}-{int(match.group(2)):02d}"
            return f"{int(match.group(1)):02d}"
    return os.environ.get("DEFAULT_EPISODE_RANGE", "01")


def normalize_episode(value):
    nums = re.findall(r"\d{1,3}", value or "")
    if len(nums) >= 2:
        return f"{int(nums[0]):02d}-{int(nums[1]):02d}"
    if len(nums) == 1:
        return f"{int(nums[0]):02d}"
    return "01"


def unique_path(path):
    path = Path(path)
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    for idx in range(2, 1000):
        candidate = parent / f"{stem} ({idx}){suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Cannot create unique path for {path}")


def copy_if_exists(src, dst, overwrite=False):
    src = Path(src)
    if not src.exists() or src.stat().st_size <= 0:
        return None
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    target = dst if overwrite else unique_path(dst)
    shutil.copy2(src, target)
    return str(target)


def update_latest_copy(src, dst):
    src = Path(src)
    dst = Path(dst)
    if src.exists() and src.stat().st_size > 0:
        shutil.copy2(src, dst)
        return str(dst)
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-dir", required=True)
    parser.add_argument("--base-dir", required=True)
    parser.add_argument("--mode", choices=["copy", "symlink"], default=os.environ.get("ORGANIZE_OUTPUT_MODE", "copy"))
    args = parser.parse_args()

    job_dir = Path(args.job_dir)
    base_dir = Path(args.base_dir)
    final_video = job_dir / "final_video_vi.mp4"
    if not final_video.exists() or final_video.stat().st_size <= 0:
        raise SystemExit(f"Missing final video: {final_video}")

    scrubbed_credentials = scrub_forbidden_credentials(job_dir)

    title = infer_title(job_dir)
    run_time = datetime.now().strftime("%Y-%m-%d %H-%M")
    if not title:
        title = f"Video Douyin - {run_time}"
    title = clean_name(title)
    episode = infer_episode(job_dir)
    episode_label = f"Tập {episode}"
    folder_name = clean_name(title)
    file_base = clean_name(f"{title} - {episode_label}")
    library_dir = base_dir / "Phim đã xử lý" / folder_name
    library_dir.mkdir(parents=True, exist_ok=True)

    outputs = {}
    outputs["video"] = copy_if_exists(final_video, library_dir / f"{file_base}.mp4")
    outputs["thumbnail"] = copy_if_exists(job_dir / "thumbnail.jpg", library_dir / f"{file_base} - thumbnail.jpg")
    outputs["vietsub"] = copy_if_exists(job_dir / "vietnamese.srt", library_dir / f"{file_base} - vietsub.srt")
    outputs["dub_subtitle"] = copy_if_exists(job_dir / "dub.srt", library_dir / f"{file_base} - dub.srt")
    outputs["log"] = copy_if_exists(job_dir / "log.txt", library_dir / f"{file_base} - log.txt")
    outputs["report"] = copy_if_exists(job_dir / "dubbing_report.json", library_dir / f"{file_base} - dubbing-report.json")

    latest_video = update_latest_copy(final_video, base_dir / "VIDEO_MOI_NHAT.mp4")
    latest_thumb = update_latest_copy(job_dir / "thumbnail.jpg", base_dir / "THUMBNAIL_MOI_NHAT.jpg")

    metadata = {
        "title": title,
        "episode_range": episode,
        "display_name": file_base,
        "safe_name": safe_slug(file_base),
        "job_dir": str(job_dir),
        "library_dir": str(library_dir),
        "outputs": outputs,
        "latest_video": latest_video,
        "latest_thumbnail": latest_thumb,
        "source_url": read_text(job_dir / "source_input.txt"),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "scrubbed_credentials": scrubbed_credentials,
        "naming_rules": {
            "keep_vietnamese_diacritics": True,
            "max_filename_chars": 120,
            "copy_mode": args.mode,
        },
    }
    metadata_path = job_dir / "final_metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    library_metadata = library_dir / f"{file_base} - metadata.json"
    library_metadata.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs["metadata"] = str(library_metadata)
    print(json.dumps(metadata, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
