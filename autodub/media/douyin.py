"""Douyin downloader.

Primary path (fast, reliable): resolve the short link to a numeric video id,
fetch the mobile share page ``iesdouyin.com/share/video/<id>/`` whose embedded
``window._ROUTER_DATA`` JSON carries the play address for exactly that video,
then download the MP4 from the ``aweme/v1/play`` endpoint (no watermark).

Fallback path (slow): drive a headless Chromium (Playwright) on the share
page and sniff CDN media requests. Only used when the share-page JSON is
missing or the direct download fails. NOTE: the desktop douyin.com video page
autoplays recommended-feed clips, so stream sniffing there can capture the
WRONG video — the fallback therefore also pins the share page.

yt-dlp cannot handle Douyin at all (the detail endpoint needs an `a_bogus`
signature it can't generate), which is why this module exists.
"""
import json
import os
import re
import subprocess
import time
import urllib.parse
from pathlib import Path

import requests

from autodub.utils import setup_logging, ensure_dir

logger = setup_logging("autodub.downloader_douyin")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)
# The share page serves its full render data to mobile browsers
_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
_REFERER = "https://www.douyin.com/"

_DASH_VIDEO_RE = re.compile(r"/media-video-")
_DASH_AUDIO_RE = re.compile(r"/media-audio-")
_CDN_HOST_RE = re.compile(r"\.(zjcdn|douyinvod|douyincdn)\.com|\.bytecdntp\.com")
_VIDEO_MIME_RE = re.compile(r"mime_type=video_mp4")
_ROUTER_DATA_RE = re.compile(r"window\._ROUTER_DATA\s*=\s*(\{.*?\})\s*</script>", re.DOTALL)

# ID patterns seen across douyin URL shapes (canonical, share page, modal route)
_ID_PATTERNS = (
    re.compile(r"/video/(\d+)"),
    re.compile(r"/share/video/(\d+)"),
    re.compile(r"[?&]modal_id=(\d+)"),
    re.compile(r"[?&]vid=(\d+)"),
)


def is_douyin_url(url: str) -> bool:
    if not url:
        return False
    url = url.strip()
    # Link share dán từ app thường thiếu scheme ("v.douyin.com/xxx") —
    # urlparse khi đó trả netloc rỗng và link bị đẩy nhầm sang yt-dlp.
    if "://" not in url:
        url = "https://" + url
    host = urllib.parse.urlparse(url).netloc.lower()
    return (host == "douyin.com" or host.endswith(".douyin.com")
            or host == "iesdouyin.com" or host.endswith(".iesdouyin.com"))


def _extract_video_id(url: str) -> str | None:
    for pattern in _ID_PATTERNS:
        m = pattern.search(url)
        if m:
            return m.group(1)
    return None


def resolve_video_id(url: str) -> str | None:
    """Resolve a Douyin URL (including v.douyin.com short links) to its video ID.

    Short links 302-redirect to an iesdouyin.com share URL that embeds the
    numeric video id. We must pin the id before touching any page: feed/share
    surfaces autoplay other clips, so "grab the first stream" is unreliable.
    """
    vid = _extract_video_id(url)
    if vid:
        return vid

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _UA},
            allow_redirects=True,
            timeout=15,
            stream=True,  # we only need the redirect chain, not the body
        )
        candidates = [resp.url] + [r.headers.get("Location", "") for r in resp.history]
        resp.close()
    except requests.RequestException as exc:
        logger.warning(f"Short-link resolution failed for {url}: {exc}")
        return None

    for candidate in candidates:
        vid = _extract_video_id(candidate)
        if vid:
            return vid
    return None


# --------------------------------------------------------------------------- #
# Primary path: share-page JSON → direct MP4
# --------------------------------------------------------------------------- #

def _fetch_share_info(video_id: str) -> dict | None:
    """Fetch video metadata from the mobile share page's embedded JSON.

    Returns {"uri", "title", "duration_ms"} or None if the page layout changed.
    """
    url = f"https://www.iesdouyin.com/share/video/{video_id}/"
    try:
        resp = requests.get(url, headers={"User-Agent": _MOBILE_UA}, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning(f"Share page fetch failed for {video_id}: {exc}")
        return None

    m = _ROUTER_DATA_RE.search(resp.text)
    if not m:
        logger.warning(f"No _ROUTER_DATA found in share page for {video_id}")
        return None

    try:
        data = json.loads(m.group(1))
        for loader_value in data.get("loaderData", {}).values():
            if not isinstance(loader_value, dict):
                continue
            items = loader_value.get("videoInfoRes", {}).get("item_list", [])
            if not items:
                continue
            item = items[0]
            if str(item.get("aweme_id", "")) != video_id:
                logger.warning(
                    f"Share page returned aweme_id={item.get('aweme_id')} "
                    f"instead of {video_id}"
                )
                return None
            uri = item.get("video", {}).get("play_addr", {}).get("uri", "")
            if not uri:
                return None
            return {
                "uri": uri,
                "title": (item.get("desc") or "").strip(),
                "duration_ms": item.get("video", {}).get("duration") or 0,
            }
    except (ValueError, KeyError, TypeError) as exc:
        logger.warning(f"Share page JSON parse failed for {video_id}: {exc}")
    return None


def _download_play_url(uri: str, dest: Path) -> int:
    """Download the MP4 via the aweme play endpoint (no watermark)."""
    quoted = urllib.parse.quote(str(uri), safe="")
    url = f"https://aweme.snssdk.com/aweme/v1/play/?video_id={quoted}&ratio=1080p&line=0"
    headers = {"User-Agent": _MOBILE_UA, "Referer": _REFERER}
    size = 0
    # Ghi ra .part rồi os.replace: đứt mạng giữa chừng không để lại file
    # cắt cụt ở đích trông như tải thành công.
    part = Path(str(dest) + ".part")
    try:
        with requests.get(url, headers=headers, stream=True,
                          allow_redirects=True, timeout=120) as r:
            r.raise_for_status()
            content_type = r.headers.get("Content-Type", "")
            if "video" not in content_type:
                raise RuntimeError(f"Play endpoint returned {content_type}, not video")
            with open(part, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
                        size += len(chunk)
        if size < 10_000:
            raise RuntimeError(f"Play endpoint returned suspiciously small file ({size}B)")
        os.replace(part, dest)
    finally:
        if part.exists():
            part.unlink(missing_ok=True)
    return size


# --------------------------------------------------------------------------- #
# Fallback path: Playwright stream sniffing on the share page
# --------------------------------------------------------------------------- #

def _bitrate_of(url: str) -> int:
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    try:
        return int(qs.get("br", ["0"])[0])
    except (ValueError, TypeError):
        return 0


def _extract_via_playwright(
    url: str,
    wait_seconds: float = 20.0,
    headless: bool = True,
) -> dict:
    """Open the Douyin page and capture direct CDN URLs for video + audio.

    Douyin detects vanilla headless Chromium and refuses to start the player.
    We launch with `--disable-blink-features=AutomationControlled` and a fully
    populated UA + viewport to look like a real browser.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        # playwright không đóng trong exe — người dùng cài qua file bat.
        raise RuntimeError(
            "Tính năng tải Douyin chưa được cài. Đúp chuột file "
            "'Cai dat tinh nang Douyin.bat' trong thư mục VoxDub, đợi cài "
            "xong rồi mở lại app.") from None

    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-features=IsolateOrigins,site-per-process",
    ]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, args=launch_args)
        # try/finally BẮT BUỘC: goto timeout hay lỗi giữa chừng mà không đóng
        # browser thì mỗi lần batch fail rò rỉ một tiến trình Chromium headless.
        try:
            context = browser.new_context(
                user_agent=_UA,
                viewport={"width": 1920, "height": 1080},
                locale="zh-CN",
            )
            # Hide webdriver flag — Douyin checks navigator.webdriver
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            page = context.new_page()

            captured = {"dash_video": [], "dash_audio": [], "progressive": []}

            def on_request(req):
                u = req.url
                if not _CDN_HOST_RE.search(u):
                    return
                if _DASH_VIDEO_RE.search(u):
                    captured["dash_video"].append(u)
                elif _DASH_AUDIO_RE.search(u):
                    captured["dash_audio"].append(u)
                elif _VIDEO_MIME_RE.search(u):
                    captured["progressive"].append(u)

            page.on("request", on_request)

            logger.info(f"Loading Douyin page: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            deadline = time.time() + wait_seconds
            while time.time() < deadline:
                if captured["progressive"] or (captured["dash_video"] and captured["dash_audio"]):
                    break
                page.wait_for_timeout(500)

            title = page.title() or ""
            title = re.sub(r"\s*[-–]\s*抖音\s*$", "", title).strip()
            canonical = page.url
        finally:
            browser.close()

    logger.info(
        f"Captured: progressive={len(captured['progressive'])} "
        f"dash_video={len(captured['dash_video'])} dash_audio={len(captured['dash_audio'])}"
    )

    video_id = _extract_video_id(canonical) or ""

    if captured["progressive"]:
        return {
            "mode": "progressive",
            "canonical_url": canonical,
            "video_id": video_id,
            "title": title,
            "video_url": max(captured["progressive"], key=_bitrate_of),
        }

    if captured["dash_video"] and captured["dash_audio"]:
        return {
            "mode": "dash",
            "canonical_url": canonical,
            "video_id": video_id,
            "title": title,
            "video_url": max(captured["dash_video"], key=_bitrate_of),
            "audio_url": max(captured["dash_audio"], key=_bitrate_of),
        }

    raise RuntimeError(
        f"No usable video stream captured from Douyin page (canonical={canonical})"
    )


def _download_stream(url: str, dest: Path) -> int:
    headers = {"User-Agent": _UA, "Referer": _REFERER}
    size = 0
    # Ghi ra .part rồi os.replace — đứt mạng không để lại file cắt cụt.
    part = Path(str(dest) + ".part")
    try:
        with requests.get(url, headers=headers, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(part, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
                        size += len(chunk)
        if size < 10_000:
            raise RuntimeError(
                f"CDN returned suspiciously small file ({size}B) — likely an "
                "error page, not the video")
        os.replace(part, dest)
    finally:
        if part.exists():
            part.unlink(missing_ok=True)
    return size


def _ffmpeg_mux(video_path: Path, audio_path: Path, output_path: Path) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-c", "copy",
        str(output_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        raise RuntimeError("ffmpeg mux treo quá 600s")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg mux failed: {proc.stderr[-500:]}")


def _ffprobe_duration(path: Path) -> float:
    try:
        out = subprocess.check_output(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=nokey=1:noprint_wrappers=1",
                str(path),
            ],
            text=True, timeout=60,
        )
        return float(out.strip())
    except Exception as e:
        logger.warning(f"ffprobe không đọc được thời lượng của {path}: {e}")
        return 0.0


def _download_via_playwright(video_id: str, out_dir: Path, final_path: Path) -> dict:
    """Fallback: sniff CDN streams from the share page with a headless browser."""
    share_url = f"https://www.iesdouyin.com/share/video/{video_id}/"
    info = _extract_via_playwright(share_url)

    # The share page may client-side redirect; verify we stayed on our video.
    if info["video_id"] and info["video_id"] != video_id:
        raise RuntimeError(
            f"Douyin redirected to a different video (requested {video_id}, "
            f"got {info['video_id']}). The video may be region-locked or removed."
        )

    if info["mode"] == "progressive":
        logger.info(f"Downloading progressive MP4 id={video_id}")
        size = _download_stream(info["video_url"], final_path)
        logger.info(f"Stream downloaded: {size:,}B")
    else:
        tmp_video = out_dir / f"_tmp_{video_id}.video.mp4"
        tmp_audio = out_dir / f"_tmp_{video_id}.audio.m4a"
        try:
            logger.info(f"Downloading DASH video stream id={video_id}")
            v_size = _download_stream(info["video_url"], tmp_video)
            logger.info(f"Downloading DASH audio stream id={video_id}")
            a_size = _download_stream(info["audio_url"], tmp_audio)
            logger.info(f"Streams downloaded: video={v_size:,}B audio={a_size:,}B")
            _ffmpeg_mux(tmp_video, tmp_audio, final_path)
        finally:
            for p in (tmp_video, tmp_audio):
                if p.exists():
                    try:
                        p.unlink()
                    except OSError:
                        pass
    return info


def download_douyin(
    url: str,
    output_dir: str,
    filename: str | None = None,
) -> dict:
    """Download a Douyin video and return metadata matching download_one() shape.

    Returned dict keys:
        input_url, canonical_url, platform, video_id, title, uploader,
        duration, filepath
    """
    if not url:
        raise ValueError("URL cannot be empty")
    url = url.strip()
    if "://" not in url:   # link share dán từ app thường thiếu scheme
        url = "https://" + url

    ensure_dir(output_dir)

    video_id = resolve_video_id(url)
    if not video_id:
        raise RuntimeError(
            f"Could not resolve a Douyin video id from {url}. "
            "Paste the video link copied from the share button."
        )
    logger.info(f"Douyin video id={video_id} ({url})")

    out_dir = Path(output_dir)
    name = filename or f"Douyin_{video_id}.mp4"
    final_path = out_dir / name
    title = ""

    # --- Primary: share-page JSON → direct MP4 (id-exact, no browser) ---
    share_info = _fetch_share_info(video_id)
    downloaded = False
    if share_info:
        title = share_info["title"]
        try:
            size = _download_play_url(share_info["uri"], final_path)
            logger.info(f"Direct download OK: {size:,}B (uri={share_info['uri']})")
            downloaded = True
        except (requests.RequestException, RuntimeError) as exc:
            logger.warning(f"Direct play download failed: {exc}; "
                           "falling back to browser capture.")

    # --- Fallback: Playwright stream sniffing (share page, id-verified) ---
    if not downloaded:
        info = _download_via_playwright(video_id, out_dir, final_path)
        title = title or info["title"]

    duration = _ffprobe_duration(final_path)
    logger.info(f"Saved: {final_path} ({duration:.1f}s)")

    return {
        "input_url": url,
        "canonical_url": f"https://www.douyin.com/video/{video_id}",
        "platform": "Douyin",
        "video_id": video_id,
        "title": title,
        "uploader": "",
        "duration": duration,
        "filepath": str(final_path),
    }
