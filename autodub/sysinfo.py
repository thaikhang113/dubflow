"""Đọc thông tin phần cứng (RAM/CPU) — không cần thư viện ngoài.

Dùng cho "bộ điều phối tài nguyên": máy ít RAM thì tự hạ số tiến trình giọng
đọc, tránh tràn bộ nhớ thay vì để hệ điều hành swap đến đứng máy. psutil KHÔNG
có trong venv chính nên đọc thẳng từ Windows API qua ctypes; máy POSIX (dev
chạy test trên CI) dùng os.sysconf. Mọi hàm trả ``None`` khi không đọc được —
bên gọi phải coi None là "không rõ" và giữ mặc định an toàn.
"""
from __future__ import annotations

import os
import sys
from functools import lru_cache

_BYTES_PER_GB = 1024 ** 3


def _windows_memory_status():
    """(total_bytes, avail_bytes) từ GlobalMemoryStatusEx, hoặc None."""
    import ctypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return status.ullTotalPhys, status.ullAvailPhys


def _posix_memory_status():
    """(total_bytes, avail_bytes) qua os.sysconf, hoặc None."""
    try:
        page = os.sysconf("SC_PAGE_SIZE")
        total = os.sysconf("SC_PHYS_PAGES") * page
        avail = os.sysconf("SC_AVPHYS_PAGES") * page
        return total, avail
    except (ValueError, OSError, AttributeError):
        return None


def _memory_status():
    try:
        if sys.platform == "win32":
            return _windows_memory_status()
        return _posix_memory_status()
    except Exception:
        return None


@lru_cache(maxsize=1)
def total_ram_gb() -> float | None:
    """Tổng RAM vật lý (GB) — bất biến nên cache được."""
    status = _memory_status()
    if status is None:
        return None
    return status[0] / _BYTES_PER_GB


def available_ram_gb() -> float | None:
    """RAM còn trống (GB) — thay đổi liên tục, KHÔNG cache."""
    status = _memory_status()
    if status is None:
        return None
    return status[1] / _BYTES_PER_GB
