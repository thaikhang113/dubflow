"""Bilibili URL and local cookie helpers."""
from __future__ import annotations

import os
import re
from urllib.parse import urlparse

_BVID_RE = re.compile(r"/video/(BV[0-9A-Za-z]+)", re.IGNORECASE)
_AUTH_COOKIES = {"SESSDATA", "DedeUserID", "bili_jct"}


def canonical_url(url: str) -> str:
    value = str(url or "").strip()
    match = _BVID_RE.search(urlparse(value).path)
    if not match:
        return value
    return f"https://www.bilibili.com/video/{match.group(1)}"


def has_login_cookies(path: str | None) -> bool:
    if not path or not os.path.isfile(path):
        return False
    found: set[str] = set()
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.startswith("#") or not line.strip():
                    continue
                fields = line.rstrip("\n").split("\t")
                if len(fields) >= 7:
                    found.add(fields[5])
    except OSError:
        return False
    return _AUTH_COOKIES.issubset(found)
