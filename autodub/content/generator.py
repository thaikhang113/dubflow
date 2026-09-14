"""Nội dung đăng bài: xuất lời thoại local, metadata qua endpoint tùy chọn.

Mỗi dự án nhận:

- ``script_original.txt`` / ``script_vi.txt`` — lời thoại thuần chữ, dán được
  vào ô mô tả của YouTube/TikTok/Facebook.
- ``thumbnail_original.jpg`` — ảnh bìa gốc của video YouTube (nếu nguồn là
  YouTube), để người dùng tự thiết kế lại.
- ``youtube_post.txt`` / ``youtube_metadata.json`` — bộ tiêu đề + mô tả + hashtag
  do mô hình ở endpoint dịch viết. Yêu cầu này có thể phát sinh phí provider.
  Hai tệp chỉ xuất hiện khi có nội dung thật.
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

#: Ký tự lời thoại tối đa đưa vào một lượt hỏi.
_SCRIPT_PROMPT_LIMIT = 6000

#: Lời nhắn. Giữ nguyên dạng ghép chuỗi: lời nhắn có chứa ngoặc nhọn của JSON
#: nên ``str.format`` sẽ hiểu nhầm đó là chỗ cần điền.
_POST_RULES = (
    "Bạn là người viết mô tả video cho nhà sáng tạo Việt Nam. Đọc lời thoại đã "
    "lồng tiếng rồi trả ĐÚNG JSON dạng "
    '{"title":"...","description":"...","hashtags":["#..."],'
    '"tiktok":{"title":"...","hashtags":["#..."]},'
    '"facebook":{"description":"...","hashtags":["#..."]}}. '
    "Quy tắc: title không quá 90 ký tự; description 2-4 câu dễ đọc; 5-8 hashtag "
    "liên quan; mỗi nền tảng một bản riêng. Không bịa nội dung ngoài lời thoại, "
    "không giải thích thêm.\n\n"
)


def _build_post_prompt(video_title: str, script: str) -> str:
    return (f"{_POST_RULES}"
            f"Tiêu đề gốc: {video_title}\n\n"
            f"Lời thoại tiếng Việt: {script}")


def _text_list(value) -> list[str]:
    """Danh sách hashtag dạng chữ, bỏ phần tử không phải chuỗi và phần tử rỗng."""
    if not isinstance(value, list):
        return []
    return [tag.strip() for tag in value if isinstance(tag, str) and tag.strip()]


def _clean_metadata(reply: dict) -> dict:
    """Giữ lại những phần mô hình trả về đúng kiểu, bỏ phần trống."""
    meta: dict = {}
    title = reply.get("title")
    title = title.strip() if isinstance(title, str) else ""
    description = reply.get("description")
    description = description.strip() if isinstance(description, str) else ""
    hashtags = _text_list(reply.get("hashtags"))
    if title:
        meta["title"] = title[:90]
    if description:
        meta["description"] = description[:2000]
    if hashtags:
        meta["hashtags"] = hashtags[:8]
    for platform in ("tiktok", "facebook"):
        block = reply.get(platform)
        if not isinstance(block, dict):
            continue
        cleaned: dict = {}
        for key in ("title", "description"):
            value = block.get(key)
            if isinstance(value, str) and (value := value.strip()):
                cleaned[key] = value[:200] if key == "title" else value[:2000]
        tags = _text_list(block.get("hashtags"))
        if tags:
            cleaned["hashtags"] = tags[:8]
        if cleaned:
            meta[platform] = cleaned
    return meta


def generate_social_metadata(script_original: str, script_translated: str,
                             video_title: str = "", job_id: str = "",
                             settings=None) -> dict:
    """Viết tiêu đề, mô tả và hashtag bằng endpoint người dùng đã cấu hình.

    App desktop không có máy chủ riêng và không giữ API Key nào, nên bước này
    đi đúng endpoint OpenAI-compatible mà trang Dịch thuật đã điền. Chưa cấu
    hình thì coi như "người dùng tự viết": trả ``{}`` để :func:`generate_content`
    bỏ qua tệp đăng bài thay vì ghi một khung toàn tiêu đề trống. Đây vẫn là
    bước phụ - lỗi ở đây không làm hỏng video.
    """
    del job_id          # giữ chữ ký cũ cho các lời gọi đang có
    script = (script_translated or script_original or "").strip()
    if not script:
        logger.info("Bỏ qua tạo tiêu đề/mô tả: lời thoại rỗng")
        return {}
    endpoint = str(getattr(settings, "translation_endpoint", "") or "").strip()
    model = str(getattr(settings, "translation_model", "") or "").strip()
    if not endpoint or not model:
        logger.info("Bỏ qua tạo tiêu đề/mô tả: chưa cấu hình endpoint dịch")
        return {}

    from autodub.providers.openai_compatible import OpenAICompatibleProvider

    prompt = _build_post_prompt(
        (video_title or "(không có tiêu đề)")[:200],
        script[:_SCRIPT_PROMPT_LIMIT])
    with requests.Session() as session:
        provider = OpenAICompatibleProvider(
            endpoint,
            str(getattr(settings, "translation_api_key", "") or ""),
            model,
            session=session,
        )
        reply = provider.complete_object(prompt, temperature=0.5)
    meta = _clean_metadata(reply if isinstance(reply, dict) else {})
    if not meta:
        logger.info("Bỏ qua tạo tiêu đề/mô tả: model trả về rỗng")
    else:
        logger.info(f"Đã viết tiêu đề, mô tả và hashtag cho {len(meta)} mục")
    return meta


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
    lines += block("TIKTOK", tiktok.get("title", ""),
                   tiktok.get("description", ""),
                   tiktok.get("hashtags", []))
    lines += block("FACEBOOK", facebook.get("title", ""),
                   facebook.get("description", ""),
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

    1. Rút lời thoại thuần chữ ra tệp (dán được vào ô mô tả ngay).
    2. Tải ảnh bìa gốc của video YouTube (nếu có) để người dùng tham chiếu.
    3. Nếu có endpoint dịch và mô hình viết ra tiêu đề / mô tả / hashtag thì mới
       ghi ``youtube_metadata.json`` và ``youtube_post.txt``; không có thì hai
       tệp này vắng mặt có chủ đích.

    Trả về dict có các khóa: metadata, metadata_file, post_file.
    """
    del video_path      # giữ chữ ký cũ cho các nơi gọi hiện có

    result: dict = {"metadata": {}, "metadata_file": None}

    script_original = extract_script_text(
        segments, "text", os.path.join(output_dir, "script_original.txt"))
    script_translated = extract_script_text(
        segments, "text_vi", os.path.join(output_dir, "script_vi.txt"))

    if source_url:
        fetch_original_thumbnail(source_url, output_dir)

    result["metadata"] = generate_social_metadata(
        script_original, script_translated, video_title=video_title,
        job_id=job_id, settings=settings)

    result["post_file"] = None
    if not result["metadata"]:
        for filename in ("youtube_metadata.json", "youtube_post.txt"):
            try:
                os.remove(os.path.join(output_dir, filename))
            except FileNotFoundError:
                pass
        return result

    metadata_path = os.path.join(output_dir, "youtube_metadata.json")
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(result["metadata"], f, ensure_ascii=False, indent=2)
    result["metadata_file"] = metadata_path

    post_path = os.path.join(output_dir, "youtube_post.txt")
    _write_post_file(post_path, result["metadata"])
    result["post_file"] = post_path
    return result
