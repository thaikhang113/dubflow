"""Kiểm tra bản phát hành mới trên GitHub Releases.

Chỉ là phần logic thuần: gọi API công khai của GitHub (không cần đăng nhập),
so sánh số phiên bản và trả về kết quả. Phần giao diện (chạy nền, hiện thông
báo) nằm ở ``autodub_gui`` — tách ra để kiểm thử được không cần mạng.
"""
from __future__ import annotations

from dataclasses import dataclass

_API_URL = "https://api.github.com/repos/{repo}/releases/latest"
_TIMEOUT_S = 10


@dataclass
class UpdateInfo:
    """Một bản phát hành mới hơn bản đang chạy."""

    version: str        # số phiên bản mới, ví dụ "2.2"
    url: str            # trang tải bản mới
    notes: str          # ghi chú phát hành (có thể trống)


def parse_version(text: str) -> tuple[int, ...]:
    """Đổi "v2.1" / "2.1.3" thành bộ số so sánh được; phần lạ coi là 0."""
    text = (text or "").strip().lstrip("vV")
    parts: list[int] = []
    for piece in text.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer(latest: str, current: str) -> bool:
    """``latest`` có mới hơn ``current`` không (bỏ qua tiền tố "v")."""
    a, b = parse_version(latest), parse_version(current)
    length = max(len(a), len(b))
    a += (0,) * (length - len(a))
    b += (0,) * (length - len(b))
    return a > b


def check_for_update(repo: str, current_version: str) -> UpdateInfo | None:
    """Hỏi GitHub xem có bản mới không. Trả về None nếu đang mới nhất.

    Lỗi mạng hay kho không tồn tại đều ném ra ngoài — nơi gọi tự quyết
    im lặng hay báo, tùy chỗ (kiểm tra nền thì im lặng, bấm tay thì báo).
    """
    import requests

    repo = (repo or "").strip().strip("/")
    if not repo or "/" not in repo:
        return None
    resp = requests.get(_API_URL.format(repo=repo), timeout=_TIMEOUT_S,
                        headers={"Accept": "application/vnd.github+json"})
    resp.raise_for_status()
    data = resp.json()
    tag = str(data.get("tag_name") or "").strip()
    if not tag or not is_newer(tag, current_version):
        return None
    return UpdateInfo(
        version=tag.lstrip("vV"),
        url=str(data.get("html_url") or f"https://github.com/{repo}/releases"),
        notes=str(data.get("body") or "").strip(),
    )
