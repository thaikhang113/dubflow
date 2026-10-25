"""Bilibili URL and local cookie helpers."""
from __future__ import annotations

import os
import re
from urllib.parse import parse_qs, urlparse

_BVID_RE = re.compile(r"/video/((?:BV[0-9A-Za-z]+)|(?:av\d+))", re.IGNORECASE)
_AUTH_COOKIES = {"SESSDATA", "DedeUserID", "bili_jct"}
_PATCHED_BILIBILI = False


def patch_bilibili_extractor() -> None:
    """Patch yt-dlp's BilibiliIE to handle pages where window.__INITIAL_STATE__ is omitted.

    Bilibili frequently omits server-rendered window.__INITIAL_STATE__ for non-logged-in
    requests. When this occurs, yt-dlp raises 'Unable to extract initial state' even though
    the official WBI detail API provides the exact same data structure under data.View.
    This patch intercepts the missing state and populates videoData from the WBI API response.
    """
    global _PATCHED_BILIBILI
    if _PATCHED_BILIBILI:
        return
    try:
        from yt_dlp.extractor.bilibili import BiliBiliIE
        from yt_dlp.utils import traverse_obj

        orig_search_json = BiliBiliIE._search_json

        def _patched_search_json(self, expr, webpage, name, video_id, *args, **kwargs):
            try:
                res = orig_search_json(self, expr, webpage, name, video_id, *args, **kwargs)
            except Exception:
                res = None
            if res is None and name == "initial state":
                headers = {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Referer": "https://www.bilibili.com/",
                }
                vid_str = str(video_id or "").strip()
                if vid_str.isdigit():
                    query = {"platform": "web", "aid": vid_str}
                else:
                    bvid = vid_str if vid_str.upper().startswith("BV") else f"BV{vid_str}"
                    query = {"platform": "web", "bvid": bvid}
                signed = self._sign_wbi(query, video_id)
                detail = self._download_json(
                    "https://api.bilibili.com/x/web-interface/wbi/view/detail",
                    video_id,
                    note="Downloading video detail via WBI API fallback",
                    query=signed,
                    headers=headers,
                    fatal=False,
                )
                view = traverse_obj(detail, ("data", "View", {dict}))
                if view:
                    res = {
                        "videoData": view,
                        "upData": traverse_obj(detail, ("data", "Card", "card", {dict})) or {},
                        "tags": traverse_obj(detail, ("data", "Tags", {list})) or [],
                    }
            return res

        BiliBiliIE._search_json = _patched_search_json
        _PATCHED_BILIBILI = True
    except Exception:
        pass


def canonical_url(url: str) -> str:
    value = str(url or "").strip()
    parsed = urlparse(value)
    host = parsed.netloc.lower()
    if host in ("bilibili.com", "b23.tv") or host.endswith((".bilibili.com", ".b23.tv")):
        patch_bilibili_extractor()
    match = _BVID_RE.search(parsed.path)
    if not match:
        return value
    result = f"https://www.bilibili.com/video/{match.group(1)}"
    part = parse_qs(parsed.query).get("p", [""])[0]
    if part.isdigit() and int(part) > 0:
        result += f"?p={int(part)}"
    return result


def has_login_cookies(path: str | None) -> bool:
    if not path or not os.path.isfile(path):
        return False
    found: set[str] = set()
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if ((line.startswith("#") and
                     not line.startswith("#HttpOnly_"))
                        or not line.strip()):
                    continue
                fields = line.rstrip("\n").split("\t")
                if len(fields) >= 7:
                    found.add(fields[5])
    except OSError:
        return False
    return _AUTH_COOKIES.issubset(found)


def save_netscape_cookies(text: str, path: str) -> None:
    """Validate and save pasted Netscape cookies without exposing values."""
    raw = str(text or "")
    if len(raw.encode("utf-8")) > 1024 * 1024:
        raise ValueError("Cookie Bilibili vượt quá 1 MiB.")
    if not raw.lstrip().startswith("# Netscape HTTP Cookie File"):
        raise ValueError("Cookie phải là định dạng Netscape.")
    records: list[list[str]] = []
    tab_lines: list[str] = []
    plain_lines: list[str] = []
    for line in raw.splitlines():
        if not line or (line.startswith("#") and
                        not line.startswith("#HttpOnly_")):
            continue
        if "\t" in line:
            tab_lines.append(line)
        else:
            plain_lines.append(line)
    if tab_lines and plain_lines:
        raise ValueError("Không trộn hai định dạng cookie.")
    if tab_lines:
        records = [line.split("\t") for line in tab_lines]
    else:
        if len(plain_lines) % 7:
            raise ValueError("Cookie có dòng sai định dạng.")
        records = [
            plain_lines[index:index + 7]
            for index in range(0, len(plain_lines), 7)
        ]
    names: set[str] = set()
    normalized: list[str] = []
    for fields in records:
        if len(fields) != 7:
            raise ValueError("Cookie có dòng sai định dạng.")
        domain, _, cookie_path, _, _, name, _ = fields
        host = domain.lstrip(".").lower()
        if host != "bilibili.com" and not host.endswith(".bilibili.com"):
            raise ValueError("Cookie chứa domain không phải Bilibili.")
        if not cookie_path.startswith("/") or not name:
            raise ValueError("Cookie có trường không hợp lệ.")
        names.add(name)
        normalized.append("\t".join(fields))
    if not _AUTH_COOKIES.issubset(names):
        raise ValueError("Cookie thiếu SESSDATA, DedeUserID hoặc bili_jct.")
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    temporary = path + ".part"
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("# Netscape HTTP Cookie File\n")
        handle.write("\n".join(normalized) + "\n")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, path)

def default_bilibili_cookies_file() -> str | None:
    """Find default Bilibili Netscape cookies file if present."""
    from autodub.utils import data_root
    candidates = [
        os.path.join(data_root(), "bilibili-cookies.txt"),
    ]
    if os.name == "nt":
        local_app = os.environ.get("LOCALAPPDATA", "")
        if local_app:
            candidates.extend([
                os.path.join(local_app, "Programs", "DubFlow", "bilibili-cookies.txt"),
                os.path.join(local_app, "DubFlow", "bilibili-cookies.txt"),
            ])
            env_file = os.path.join(local_app, "DubFlow", ".env")
            if os.path.isfile(env_file):
                try:
                    with open(env_file, encoding="utf-8") as f:
                        for line in f:
                            if line.startswith("BILIBILI_COOKIES_FILE="):
                                val = line.split("=", 1)[1].strip()
                                if val:
                                    candidates.append(val)
                except Exception:
                    pass
    for p in candidates:
        if p and has_login_cookies(p):
            return p
    return None

