"""Sinh nội dung đăng bài: tiêu đề, mô tả, hashtag cho từng nền tảng.

Mỗi dự án nhận hai nhóm tệp, mỗi tệp một việc:

- ``youtube_post.txt`` — nội dung đăng bài (YouTube, TikTok, Facebook).
- ``script_original.txt`` / ``script_vi.txt`` — lời thoại thuần chữ.

Phần chữ do máy chủ VoxDub viết (app không giữ API Key nào). Ảnh bìa AI đã bỏ
hẳn khỏi sản phẩm — ảnh bìa gốc của video vẫn được tải về làm tham chiếu nếu
người dùng muốn tự thiết kế.
"""
import json
import os
import re

import requests

from autodub.utils import setup_logging

logger = setup_logging("autodub.content_generator")


def _extract_video_id(url: str) -> str | None:
    """Lấy mã video YouTube từ một liên kết."""
    if not url:
        return None
    patterns = [
        r"(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})",
        r"(?:shorts/)([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def fetch_original_thumbnail(url: str, output_dir: str) -> str | None:
    """Tải ảnh bìa gốc của video YouTube."""
    video_id = _extract_video_id(url)
    if not video_id:
        return None

    thumb_urls = [
        f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
        f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
    ]
    for thumb_url in thumb_urls:
        try:
            resp = requests.get(thumb_url, timeout=10)
            if resp.status_code == 200 and len(resp.content) > 1000:
                path = os.path.join(output_dir, "thumbnail_original.jpg")
                with open(path, "wb") as f:
                    f.write(resp.content)
                logger.info(f"Đã tải ảnh bìa gốc: {path}")
                return path
        except requests.RequestException:
            continue
    return None


def extract_script_text(segments: list[dict], text_field: str,
                        output_path: str) -> str:
    """Rút lời thoại thuần chữ ra tệp .txt và trả về chính chuỗi đó."""
    lines = []
    for seg in segments:
        text = str(seg.get(text_field) or seg.get("text", "")).strip()
        if text:
            lines.append(text)
    script_text = " ".join(lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(script_text)
    return script_text


# ------------------------------------------------------- nội dung đăng bài -- #

def generate_social_metadata(script_original: str, script_translated: str,
                             video_title: str = "", job_id: str = "") -> dict:
    """Nhờ máy chủ viết tiêu đề, mô tả và hashtag.

    Đây là bước phụ: hỏng thì video vẫn xong, chỉ thiếu phần đăng bài. Vì vậy
    mọi lỗi đều được nuốt và ghi log, trừ khi hết Vox — trường hợp đó lớp
    trên cần biết để hiện lời mời nạp thêm.
    """
    from autodub.saas_client import (
        InsufficientCreditError, SaasError, get_client, is_configured,
        new_job_id)
    from autodub.text.translate_common import HOLD

    if not is_configured():
        # Chạy thuần trên máy — không có máy chủ để nhờ viết. Video vẫn xong.
        logger.info("Chưa cấu hình máy chủ — bỏ qua phần nội dung đăng bài")
        return {}

    try:
        metadata = get_client().generate_post(
            script_original, script_translated,
            job_id=job_id or new_job_id(), video_title=video_title,
            hold_id=HOLD.hold_id)
    except InsufficientCreditError:
        raise
    except SaasError as e:
        logger.error(f"Viết nội dung đăng bài lỗi ({str(e)[:120]}) — bỏ qua "
                     "phần đăng bài (không ảnh hưởng video)")
        return {}
    if metadata:
        logger.info("Đã viết xong nội dung đăng bài: "
                    f"«{str(metadata.get('title', ''))[:50]}»")
    return metadata or {}


# ------------------------------------------------------------- ghi ra tệp -- #

def _write_post_file(path: str, meta: dict) -> None:
    """``youtube_post.txt`` — nội dung đăng bài cho ba nền tảng."""
    tiktok = meta.get("tiktok") or {}
    facebook = meta.get("facebook") or {}
    bar = "=" * 60

    def block(name: str, title: str, description: str,
              hashtags: list) -> list[str]:
        rows = [bar, name, bar, "", f"TIÊU ĐỀ:\n{title}", ""]
        if description:
            rows += [f"MÔ TẢ:\n{description}", ""]
        rows += [f"HASHTAG:\n{' '.join(hashtags or [])}", ""]
        return rows

    lines: list[str] = []
    lines += block("YOUTUBE", meta.get("title", ""),
                   meta.get("description", ""), meta.get("hashtags", []))
    lines += block("TIKTOK", tiktok.get("title", ""), "",
                   tiktok.get("hashtags", []))
    lines += block("FACEBOOK", facebook.get("title", ""), "",
                   facebook.get("hashtags", []))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def generate_content(
    segments: list[dict],
    source_url: str | None,
    output_dir: str,
    settings,
    video_path: str | None = None,
    video_title: str = "",
    job_id: str = "",
) -> dict:
    """Sinh phần nội dung đăng bài của một dự án.

    Các bước:

    1. Rút lời thoại thuần chữ ra tệp (nhẹ, rẻ khi gửi lên máy chủ).
    2. Tải ảnh bìa gốc của video YouTube (nếu có) để người dùng tham chiếu.
    3. Nhờ máy chủ viết tiêu đề / mô tả / hashtag rồi ghi ra ``youtube_post.txt``.

    Trả về dict có các khóa: metadata, metadata_file, post_file.
    """
    del settings, video_path      # giữ chữ ký cũ cho các nơi gọi hiện có

    result: dict = {"metadata": {}, "metadata_file": None}

    script_original = extract_script_text(
        segments, "text", os.path.join(output_dir, "script_original.txt"))
    script_translated = extract_script_text(
        segments, "text_vi", os.path.join(output_dir, "script_vi.txt"))

    if source_url:
        fetch_original_thumbnail(source_url, output_dir)

    result["metadata"] = generate_social_metadata(
        script_original, script_translated, video_title=video_title,
        job_id=job_id)

    metadata_path = os.path.join(output_dir, "youtube_metadata.json")
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(result["metadata"], f, ensure_ascii=False, indent=2)
    result["metadata_file"] = metadata_path

    post_path = os.path.join(output_dir, "youtube_post.txt")
    _write_post_file(post_path, result["metadata"])
    result["post_file"] = post_path
    return result
