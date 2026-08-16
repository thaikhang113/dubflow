"""Bilibili URL and local cookie helpers."""
from __future__ import annotations

import os
import re
from urllib.parse import parse_qs, urlparse

_BVID_RE = re.compile(r"/video/(BV[0-9A-Za-z]+)", re.IGNORECASE)
_AUTH_COOKIES = {"SESSDATA", "DedeUserID", "bili_jct"}


def canonical_url(url: str) -> str:
    value = str(url or "").strip()
    parsed = urlparse(value)
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
