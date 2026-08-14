"""Video download via yt-dlp, with Douyin routed through Playwright."""
import os
import re
import time
from urllib.parse import urlparse, parse_qs

import yt_dlp

from autodub.utils import setup_logging, ensure_dir, save_json_atomic

logger = setup_logging("autodub.downloader")

def _extract_info_with_retry(ydl, url: str, attempts: int = 3) -> dict:
    """Retry transient Bilibili metadata failures before failing the job."""
    for attempt in range(attempts):
        try:
            return ydl.extract_info(url, download=True)
        except Exception as exc:
            message = str(exc)
            transient = re.search(r"\b(412|429|500|502|503|504)\b", message)
            if not transient or attempt == attempts - 1:
                raise
            delay = 2 * (attempt + 1)
            logger.warning(
                f"yt-dlp metadata retry {attempt + 1}/{attempts - 1} "
                f"after HTTP {transient.group(1)}; waiting {delay}s"
            )
            time.sleep(delay)


def _save_meta(output_dir: str, title: str, uploader: str = "") -> None:
    """Lưu title/uploader vào ``data/video_meta.json`` cạnh video tải về.

    Title là ngữ cảnh miễn phí, giá trị cao cho bước phân tích/dịch/metadata —
    trước đây bị vứt đi ngay sau khi tải. Best-effort: lỗi ghi không được
    làm hỏng lượt tải.
    """
    title = (title or "").strip()
    if not title:
        return
    try:
        from autodub.workdir import data_path
        save_json_atomic({"title": title, "uploader": (uploader or "").strip()},
                         data_path(output_dir, "video_meta.json",
                                   create_dir=True))
    except OSError as e:
        logger.warning(f"Không lưu được video_meta.json: {e}")


def normalize_url(url: str) -> str:
    """Rewrite non-canonical Douyin/TikTok URLs to a form yt-dlp can extract.

    Douyin's web app uses modal-style routes (e.g. /jingxuan?modal_id=<id>,
    /discover?modal_id=<id>) where the actual video id lives in the query
    string. yt-dlp's douyin extractor expects /video/<id>, so we rewrite.
    """
    if not url:
        return url
    url = url.strip()
    parsed = urlparse(url)
    host = parsed.netloc.lower()

    if "douyin.com" in host:
        qs = parse_qs(parsed.query)
        modal_id = qs.get("modal_id", [None])[0]
        if modal_id and modal_id.isdigit():
            return f"https://www.douyin.com/video/{modal_id}"

    return url


def download_video(
    url: str, output_dir: str, cookies_from_browser: str | None = None,
    cookies_file: str | None = None,
    douyin_cookies_file: str | None = None,
) -> str:
    if not url:
        raise ValueError("URL cannot be empty")

    ensure_dir(output_dir)

    # Douyin's yt-dlp extractor is broken upstream (requires `a_bogus`
    # signature). Route Douyin URLs (including v.douyin.com short links)
    # through the Playwright-based fallback.
    from autodub.media.douyin import is_douyin_url, download_douyin
    if is_douyin_url(url):
        logger.info(f"Routing to Playwright Douyin extractor: {url}")
        info = download_douyin(
            url, output_dir, cookies_file=douyin_cookies_file)
        _save_meta(output_dir, info.get("title", ""), info.get("uploader", ""))
        return info["filepath"]

    from autodub.media.bilibili import canonical_url
    canonical = canonical_url(normalize_url(url))
    if canonical != url:
        logger.info(f"Normalized URL: {url} -> {canonical}")

    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": os.path.join(output_dir, "%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
        "quiet": False,
        "no_warnings": False,
        # Mạng chập chờn: tự thử lại thay vì fail cả video trong batch.
        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 30,
    }
    if cookies_from_browser:
        ydl_opts["cookiesfrombrowser"] = (cookies_from_browser,)
    if cookies_file:
        ydl_opts["cookiefile"] = cookies_file

    logger.info(f"Downloading video from: {canonical}")

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = _extract_info_with_retry(ydl, canonical)
        video_id = info.get("id", "video")
        ext = info.get("ext", "mp4")
        filepath = (_ydl_reported_path(info)
                    or os.path.join(output_dir, f"{video_id}.{ext}"))

        if not os.path.exists(filepath):
            for f in sorted(os.listdir(output_dir)):
                if f.startswith(video_id) and not _is_partial_name(f):
                    filepath = os.path.join(output_dir, f)
                    break

    if not os.path.exists(filepath):
        raise RuntimeError(f"Download failed: file not found at {filepath}")

    _save_meta(output_dir, info.get("title", ""), info.get("uploader", ""))
    logger.info(f"Downloaded: {filepath}")
    return filepath


def build_ydl_opts(
    output_dir: str,
    cookies_from_browser: str | None = None,
    cookies_file: str | None = None,
) -> dict:
    """yt-dlp options for the standalone `autodub download` command."""
    opts = {
        # Use extractor + id as filename so TikTok/Douyin/YouTube don't collide
        "outtmpl": os.path.join(output_dir, "%(extractor_key)s_%(id)s.%(ext)s"),
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "quiet": False,
        "no_warnings": False,
        "noprogress": False,
        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 30,
    }
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    if cookies_file:
        opts["cookiefile"] = cookies_file
    return opts


def _ydl_reported_path(info: dict) -> str | None:
    """The file path yt-dlp itself reports for the finished download."""
    try:
        path = (info.get("requested_downloads") or [{}])[0].get("filepath")
    except (AttributeError, IndexError, TypeError):
        return None
    return path if path and os.path.exists(path) else None


def _is_partial_name(name: str) -> bool:
    """True for yt-dlp intermediate files (.part, .ytdl, .f299.mp4...)."""
    lower = name.lower()
    if lower.endswith((".part", ".ytdl", ".temp")):
        return True
    # Pre-merge single streams look like <id>.f<format_id>.<ext>
    return bool(re.search(r"\.f\d+\.\w+$", lower))


def _resolve_filepath(info: dict, output_dir: str) -> str:
    """yt-dlp may rename during merge; locate the actual saved file."""
    # yt-dlp tells us the real path — trust it first (also covers ids with
    # characters that were sanitized out of the filename).
    reported = _ydl_reported_path(info)
    if reported:
        return reported

    extractor = info.get("extractor_key", info.get("extractor", "video"))
    video_id = info.get("id", "video")
    ext = info.get("ext", "mp4")

    expected = os.path.join(output_dir, f"{extractor}_{video_id}.{ext}")
    if os.path.exists(expected):
        return expected

    prefix = f"{extractor}_{video_id}"
    for f in sorted(os.listdir(output_dir)):
        # .part/.fNNN là file trung gian — trả về chúng là đưa file hỏng
        # vào pipeline.
        if f.startswith(prefix) and not _is_partial_name(f):
            return os.path.join(output_dir, f)

    raise RuntimeError(f"Downloaded but file not found (prefix={prefix})")


def download_one(
    url: str,
    output_dir: str,
    cookies_from_browser: str | None = None,
    cookies_file: str | None = None,
    douyin_cookies_file: str | None = None,
) -> dict:
    """Download a single URL and return metadata + saved filepath.

    Douyin URLs (including short-link v.douyin.com/...) are routed to a
    Playwright-based extractor because yt-dlp's Douyin path is broken upstream.
    All other sites continue through yt-dlp.
    """
    from autodub.media.douyin import is_douyin_url, download_douyin
    if is_douyin_url(url):
        logger.info(f"Routing to Playwright Douyin extractor: {url}")
        return download_douyin(
            url, output_dir, cookies_file=douyin_cookies_file)

    canonical = normalize_url(url)
    if canonical != url:
        logger.info(f"Normalized: {url} -> {canonical}")

    ydl_opts = build_ydl_opts(output_dir, cookies_from_browser, cookies_file)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = _extract_info_with_retry(ydl, canonical)

    filepath = _resolve_filepath(info, output_dir)

    return {
        "input_url": url,
        "canonical_url": canonical,
        "platform": info.get("extractor_key", info.get("extractor", "")),
        "video_id": info.get("id", ""),
        "title": info.get("title", ""),
        "uploader": info.get("uploader", ""),
        "duration": info.get("duration", 0),
        "filepath": filepath,
    }
