"""Hàm định dạng chuỗi hiển thị — Python thuần, không phụ thuộc Qt.

Tách riêng để vừa dùng được trong widget vừa kiểm thử được bằng pytest.
"""
from __future__ import annotations

import datetime

_SEC_PER_MIN = 60
_SEC_PER_HOUR = 3600
_SEC_PER_DAY = 86400
_BYTES_PER_KB = 1024.0
_PLACEHOLDER = "--:--"
_UNKNOWN = "—"


def format_duration(seconds) -> str:
    """Đổi số giây thành 'MM:SS' hoặc 'H:MM:SS'."""
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return _PLACEHOLDER
    minutes, sec = divmod(abs(total), _SEC_PER_MIN)
    hours, minutes = divmod(minutes, _SEC_PER_MIN)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def format_timecode(seconds) -> str:
    """Đổi số giây thành 'HH:MM:SS.mmm', dùng cho danh sách phụ đề."""
    try:
        total = max(0.0, float(seconds))
    except (TypeError, ValueError):
        total = 0.0
    hours = int(total // _SEC_PER_HOUR)
    minutes = int((total % _SEC_PER_HOUR) // _SEC_PER_MIN)
    sec = total % _SEC_PER_MIN
    return f"{hours:02d}:{minutes:02d}:{sec:06.3f}"


def format_date(ts) -> str:
    """Đổi dấu thời gian thành 'dd/mm/YYYY HH:MM'."""
    if isinstance(ts, (int, float)):
        try:
            return datetime.datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")
        except (OSError, OverflowError, ValueError):
            return _UNKNOWN
    return str(ts)[:16]


def format_size(num_bytes) -> str:
    """Đổi số byte thành chuỗi ngắn gọn như '980 KB' hay '4.5 GB'."""
    try:
        value = float(num_bytes)
    except (TypeError, ValueError):
        return _UNKNOWN
    if value < 1:
        return "0 KB"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < _BYTES_PER_KB or unit == "TB":
            if unit in ("B", "KB"):
                return f"{value:.0f} {unit}"
            return f"{value:.1f} {unit}"
        value /= _BYTES_PER_KB
    return f"{value:.1f} TB"


def format_hours(seconds) -> str:
    """Tổng thời gian đã xử lý: '45 giây', '12 phút' hoặc '3.2 giờ'."""
    try:
        total = float(seconds)
    except (TypeError, ValueError):
        return _UNKNOWN
    if total <= 0:
        return "0 phút"
    if total < _SEC_PER_MIN:
        return f"{int(total)} giây"
    if total < _SEC_PER_HOUR:
        return f"{int(total // _SEC_PER_MIN)} phút"
    return f"{total / _SEC_PER_HOUR:.1f} giờ"


def format_eta(seconds) -> str:
    """Thời gian còn lại viết cho người đọc: 'khoảng 2 phút'."""
    try:
        total = float(seconds)
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    if total < _SEC_PER_MIN:
        return f"khoảng {int(total)} giây"
    if total < _SEC_PER_HOUR:
        return f"khoảng {int(round(total / _SEC_PER_MIN))} phút"
    hours = int(total // _SEC_PER_HOUR)
    minutes = int((total % _SEC_PER_HOUR) // _SEC_PER_MIN)
    if minutes:
        return f"khoảng {hours} giờ {minutes} phút"
    return f"khoảng {hours} giờ"


def format_relative(ts, now: float | None = None) -> str:
    """Thời điểm tương đối: 'vừa xong', '3 phút trước', '2 ngày trước'."""
    if now is None:
        now = datetime.datetime.now().timestamp()
    try:
        delta = float(now) - float(ts)
    except (TypeError, ValueError):
        return ""
    if delta < 0:
        delta = 0.0
    if delta < 45:
        return "vừa xong"
    if delta < _SEC_PER_HOUR:
        return f"{int(delta // _SEC_PER_MIN)} phút trước"
    if delta < _SEC_PER_DAY:
        return f"{int(delta // _SEC_PER_HOUR)} giờ trước"
    days = int(delta // _SEC_PER_DAY)
    if days < 30:
        return f"{days} ngày trước"
    return format_date(ts)[:10]
