"""Local Netscape cookie helpers for Douyin requests and browser sessions."""
from __future__ import annotations

import http.cookiejar
import os
from pathlib import Path

_MAX_BYTES = 1024 * 1024
_ALLOWED_SUFFIXES = (
    "douyin.com",
    "iesdouyin.com",
    "snssdk.com",
)


def _allowed_domain(domain: str) -> bool:
    host = domain.lstrip(".").lower()
    host = host.removeprefix("#httponly_")
    return any(host == suffix or host.endswith("." + suffix)
               for suffix in _ALLOWED_SUFFIXES)


def validate_douyin_cookies(text: str) -> list[str]:
    raw = str(text or "")
    if len(raw.encode("utf-8")) > _MAX_BYTES:
        raise ValueError("Cookie Douyin vượt quá 1 MiB.")
    if not raw.lstrip().startswith("# Netscape HTTP Cookie File"):
        raise ValueError("Cookie Douyin phải là định dạng Netscape.")

    records = []
    for line in raw.splitlines():
        if not line.strip() or (line.startswith("#")
                                and not line.startswith("#HttpOnly_")):
            continue
        fields = line.split("\t")
        if len(fields) != 7:
            raise ValueError("Cookie Douyin có dòng sai định dạng.")
        domain, _, cookie_path, _, _, name, _ = fields
        if not _allowed_domain(domain):
            raise ValueError("Cookie chứa domain không phải Douyin.")
        if not cookie_path.startswith("/") or not name:
            raise ValueError("Cookie Douyin có trường không hợp lệ.")
        records.append(line)
    if not records:
        raise ValueError("Cookie Douyin không có bản ghi hợp lệ.")
    return records


def save_douyin_cookies(text: str, path: str) -> None:
    records = validate_douyin_cookies(text)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(str(target) + ".part")
    temporary.write_text(
        "# Netscape HTTP Cookie File\n" + "\n".join(records) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, target)


def load_douyin_cookies(path: str | None) -> http.cookiejar.MozillaCookieJar:
    if not path:
        return http.cookiejar.MozillaCookieJar()
    if not os.path.isfile(path):
        raise ValueError("Không tìm thấy tệp cookie Douyin.")
    jar = http.cookiejar.MozillaCookieJar(path)
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Không đọc được cookie Douyin: {exc}") from exc
    for cookie in jar:
        if not _allowed_domain(cookie.domain):
            raise ValueError("Cookie chứa domain không phải Douyin.")
    return jar


def playwright_cookies(path: str | None) -> list[dict]:
    cookies = []
    for cookie in load_douyin_cookies(path):
        item = {
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain,
            "path": cookie.path or "/",
            "secure": bool(cookie.secure),
        }
        if cookie.expires:
            item["expires"] = cookie.expires
        cookies.append(item)
    return cookies
