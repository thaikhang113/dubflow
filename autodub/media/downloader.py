"""Video download via yt-dlp, with Douyin routed through Playwright."""
import http.client
import os
import re
import socket
import threading
import time
from collections.abc import Callable
from urllib.parse import parse_qs, urlparse

import yt_dlp

from autodub.progress import PipelineCancelled
from autodub.utils import (
    candidate_bin_dirs,
    ensure_bin_in_path,
    ensure_dir,
    save_json_atomic,
    setup_logging,
)

logger = setup_logging("autodub.downloader")

ProgressCallback = Callable[[dict], None]


def format_download_progress(data: dict) -> str:
    """Format download metrics into a compact human-readable progress string.

    Example: '[download]  35.4% of ~2.80GiB at 14.5MiB/s ETA 02:08'
    """
    percent = data.get("percent")
    pct_str = f"{percent:.1f}%" if isinstance(percent, (int, float)) else ""

    total = data.get("total_bytes")
    if total and total > 0:
        if total >= 1024**3:
            total_str = f"~{total / (1024**3):.2f}GiB"
        else:
            total_str = f"~{total / (1024**2):.1f}MiB"
    else:
        total_str = ""

    speed = data.get("speed_bytes_s")
    if speed and speed > 0:
        if speed >= 1024**3:
            speed_str = f"{speed / (1024**3):.2f}GiB/s"
        elif speed >= 1024**2:
            speed_str = f"{speed / (1024**2):.1f}MiB/s"
        else:
            speed_str = f"{speed / 1024:.1f}KiB/s"
    else:
        speed_str = ""

    eta = data.get("eta_s")
    if eta is not None and eta >= 0:
        m, s = divmod(int(eta), 60)
        h, m = divmod(m, 60)
        eta_str = f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
    else:
        eta_str = ""

    parts = []
    if pct_str:
        if total_str:
            parts.append(f"{pct_str} of {total_str}")
        else:
            parts.append(pct_str)
    if speed_str:
        parts.append(f"at {speed_str}")
    if eta_str:
        parts.append(f"ETA {eta_str}")

    return f"[download]  {' '.join(parts)}" if parts else "[download]  đang tải..."


def _emit_progress(
    callback: ProgressCallback | None,
    status: str,
    downloaded: int = 0,
    total: int | None = None,
    speed: float | None = None,
    eta: int | None = None,
) -> None:
    if callback is None:
        return
    percent = None
    if total and total > 0:
        percent = min(100.0, max(0.0, round(downloaded * 100.0 / total, 1)))
    if status == "finished":
        percent = 100.0
    try:
        callback({
            "status": status,
            "downloaded_bytes": max(0, int(downloaded or 0)),
            "total_bytes": int(total) if total else None,
            "speed_bytes_s": float(speed) if speed else None,
            "eta_s": int(eta) if eta is not None else None,
            "percent": percent,
        })
    except Exception:
        pass

#: Lỗi TOÀN VẸN DỮ LIỆU: kết nối đứt giữa chừng nên thân phản hồi ngắn hơn
#: Content-Length. yt-dlp bọc chúng thành ContentTooShortError với thông điệp
#: kiểu "975 bytes read, 469233162 more expected" rồi tự resume ở lần thử sau —
#: tầng app PHẢI coi là tạm thời. Đây đúng là chuỗi của sự cố Bilibili 1080p:
#: "('Connection broken: IncompleteRead(975 bytes read, 469233162 more
#: expected)', IncompleteRead(...))".
_INCOMPLETE_RE = re.compile(
    r"incompleteread|connection\s+broken|bytes\s+read|content\s+too\s+short",
    re.IGNORECASE,
)

#: Chỉ các mã HTTP này mới đáng thử lại — giữ nguyên tập cũ (412 Bilibili,
#: 429 rate limit, 5xx) và thêm 408/425/522/524 vốn cũng là mã tạm thời.
#: 403/404/410 KHÔNG nằm ở đây: link hết hạn hay sai thì thử lại chỉ tốn
#: thời gian, phải báo người dùng ngay.
_TRANSIENT_HTTP = frozenset({408, 412, 425, 429, 500, 502, 503, 504, 522, 524})
_HTTP_CODE_RE = re.compile(r"\b(\d{3})\b")

#: Lỗi ĐỨT KẾT NỐI nhưng không mang mã HTTP nào (mất mạng, timeout ở tầng
#: socket). Phải thử lại — nếu không, app bỏ cuộc ngay ở lần thử đầu đúng
#: lúc mạng chập chờn nhất.
_TRANSIENT_MSG_RE = re.compile(
    r"read\s+timed?\s*out|timed\s*out|connection\s+(?:reset|refused|aborted)"
    r"|connection\s+error|remote\s+end\s+closed|network\s+is\s+unreachable"
    r"|temporar(?:y|ily)\s+(?:failure|unavailable)"
    r"|\b50[234]\b|service\s+unavailable|bad\s+gateway|gateway\s+time-?out"
    r"|too\s+many\s+requests|rate\s*limit",
    re.IGNORECASE,
)

#: Ngoại lệ mạng/tạm thời của thư viện chuẩn — yt-dlp, requests và urllib3 đều
#: ném ra những lớp này (hoặc lớp con của chúng). IncompleteRead là lớp duy nhất
#: ở đây KHÔNG phải OSError, nên phải kể tên riêng.
_TRANSIENT_EXC = (
    http.client.IncompleteRead,
    ConnectionError,
    socket.timeout,
    TimeoutError,
)


def is_transient_download_error(error: object) -> bool:
    """Lỗi tải này có đáng thử lại không?

    Phân loại theo **loại ngoại lệ** và **mã HTTP**, không dò chuỗi tự do.
    Cách cũ (regex trên chuỗi) sai cả hai chiều:

    * âm tính giả — chuỗi thật của sự cố Bilibili không chứa "timeout" hay
      "connection reset" nào, nên app bỏ cuộc ngay ở lần thử đầu;
    * dương tính giả — "Content too short (expected 469233162, served 976)"
      khớp chữ "connection error" nằm trong phần thông tin nền.

    Thứ tự xét: ngoại lệ toàn vẹn/mạng → dấu hiệu cắt cụt trong thông điệp →
    mã HTTP tạm thời. Có mã HTTP nhưng không nằm trong danh sách tạm thời
    (403/404/410) thì trả False — yt-dlp ném cùng một lớp HTTPError cho cả
    403 lẫn 503 nên không thể chỉ nhìn loại ngoại lệ.
    """
    if isinstance(error, _TRANSIENT_EXC):
        return True
    message = str(error)
    if _INCOMPLETE_RE.search(message) or _TRANSIENT_MSG_RE.search(message):
        return True
    # Có mã HTTP nhưng KHÔNG nằm trong tập tạm thời (403/404/410...) → vĩnh
    # viễn. Không có mã nào (lỗi mạng thuần) thì đã xét ở trên.
    codes = {int(value) for value in _HTTP_CODE_RE.findall(message)}
    return bool(codes & _TRANSIENT_HTTP)


def _extract_info_with_retry(ydl, url: str, attempts: int = 3) -> dict:
    """Retry transient Bilibili metadata failures before failing the job."""
    for attempt in range(attempts):
        try:
            return ydl.extract_info(url, download=True)
        except Exception as exc:
            if not is_transient_download_error(exc) or attempt == attempts - 1:
                raise
            delay = 2 * (attempt + 1)
            logger.warning(
                f"yt-dlp retry {attempt + 1}/{attempts - 1} sau lỗi tạm thời "
                f"({type(exc).__name__}); chờ {delay}s"
            )
            time.sleep(delay)
    # Vòng lặp luôn return hoặc raise khi attempts >= 1; xuống tới đây nghĩa là
    # gọi với attempts <= 0 - nói rõ thay vì trả None cho nơi cần dict.
    raise RuntimeError(f"_extract_info_with_retry: attempts={attempts} vô nghĩa")


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
    progress: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
    fragment_workers: int = 2,
) -> str:
    if not url:
        raise ValueError("URL cannot be empty")
    if cancel_event is not None and cancel_event.is_set():
        raise PipelineCancelled("Video download cancelled")

    ensure_dir(output_dir)

    # Douyin's yt-dlp extractor is broken upstream (requires `a_bogus`
    # signature). Route Douyin URLs (including v.douyin.com short links)
    # through the Playwright-based fallback.
    from autodub.media.douyin import download_douyin, is_douyin_url
    if is_douyin_url(url):
        logger.info(f"Routing to Playwright Douyin extractor: {url}")
        info = download_douyin(
            url, output_dir, cookies_file=douyin_cookies_file,
            progress=progress, cancel_event=cancel_event)
        _save_meta(output_dir, info.get("title", ""), info.get("uploader", ""))
        return info["filepath"]

    from autodub.media.bilibili import canonical_url
    canonical = canonical_url(normalize_url(url))
    if canonical != url:
        logger.info(f"Normalized URL: {url} -> {canonical}")

    if not cookies_file and not cookies_from_browser and ("bilibili.com" in url or "bilibili.com" in canonical):
        try:
            from autodub.media.bilibili import default_bilibili_cookies_file
            cookies_file = default_bilibili_cookies_file()
        except Exception:
            pass

    ensure_bin_in_path()
    ydl_opts = {
        "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080][ext=mp4]/best[ext=mp4]/best",
        "outtmpl": os.path.join(output_dir, "%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": False,
        "no_warnings": False,
        # Mạng chập chờn: tự thử lại thay vì fail cả video trong batch.
        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 30,
        "concurrent_fragment_downloads": max(1, min(16, int(fragment_workers))),
    }
    bin_dirs = candidate_bin_dirs()
    if bin_dirs:
        ydl_opts["ffmpeg_location"] = bin_dirs[0]
    if cookies_from_browser:
        ydl_opts["cookiesfrombrowser"] = (cookies_from_browser,)
    if cookies_file:
        ydl_opts["cookiefile"] = cookies_file
    if progress is not None or cancel_event is not None:
        def progress_hook(data: dict) -> None:
            if cancel_event is not None and cancel_event.is_set():
                raise PipelineCancelled("Video download cancelled")
            status = data.get("status", "")
            if status not in ("downloading", "finished"):
                return
            _emit_progress(
                progress,
                status,
                downloaded=data.get("downloaded_bytes", 0),
                total=(data.get("total_bytes")
                       or data.get("total_bytes_estimate")),
                speed=data.get("speed"),
                eta=data.get("eta"),
            )
        ydl_opts["progress_hooks"] = [progress_hook]

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
    fragment_workers: int = 2,
) -> dict:
    """yt-dlp options for the standalone `autodub download` command."""
    ensure_bin_in_path()
    opts = {
        # Use extractor + id as filename so TikTok/Douyin/YouTube don't collide
        "outtmpl": os.path.join(output_dir, "%(extractor_key)s_%(id)s.%(ext)s"),
        "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080][ext=mp4]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": False,
        "no_warnings": False,
        "noprogress": False,
        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 30,
        "concurrent_fragment_downloads": max(1, min(16, int(fragment_workers))),
    }
    bin_dirs = candidate_bin_dirs()
    if bin_dirs:
        opts["ffmpeg_location"] = bin_dirs[0]
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
    fragment_workers: int = 2,
    progress: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> dict:
    """Download a single URL and return metadata + saved filepath.

    Douyin URLs (including short-link v.douyin.com/...) are routed to a
    Playwright-based extractor because yt-dlp's Douyin path is broken upstream.
    All other sites continue through yt-dlp.
    """
    if cancel_event is not None and cancel_event.is_set():
        raise PipelineCancelled("Video download cancelled")

    from autodub.media.douyin import download_douyin, is_douyin_url
    if is_douyin_url(url):
        logger.info(f"Routing to Playwright Douyin extractor: {url}")
        douyin_kwargs = {}
        if progress is not None:
            douyin_kwargs["progress"] = progress
        if cancel_event is not None:
            douyin_kwargs["cancel_event"] = cancel_event
        return download_douyin(
            url, output_dir, cookies_file=douyin_cookies_file, **douyin_kwargs)

    from autodub.media.bilibili import canonical_url
    canonical = canonical_url(normalize_url(url))
    if canonical != url:
        logger.info(f"Normalized: {url} -> {canonical}")

    if not cookies_file and not cookies_from_browser and ("bilibili.com" in url or "bilibili.com" in canonical):
        try:
            from autodub.media.bilibili import default_bilibili_cookies_file
            cookies_file = default_bilibili_cookies_file()
        except Exception:
            pass

    ydl_opts = build_ydl_opts(
        output_dir, cookies_from_browser, cookies_file, fragment_workers)

    if progress is not None or cancel_event is not None:
        def progress_hook(data: dict) -> None:
            if cancel_event is not None and cancel_event.is_set():
                raise PipelineCancelled("Video download cancelled")
            status = data.get("status", "")
            if status not in ("downloading", "finished"):
                return
            _emit_progress(
                progress,
                status,
                downloaded=data.get("downloaded_bytes", 0),
                total=(data.get("total_bytes")
                       or data.get("total_bytes_estimate")),
                speed=data.get("speed"),
                eta=data.get("eta"),
            )
        ydl_opts["progress_hooks"] = [progress_hook]

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
