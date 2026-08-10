"""Định danh máy — mã thiết bị dùng để gắn ví Vox.

Không có tài khoản người dùng: chính chiếc máy này LÀ danh tính. Mã thiết bị
được băm từ ba thứ gắn với phần cứng và hệ điều hành, không phải từ thứ gì
người dùng đặt được:

- ``MachineGuid`` trong registry — Windows sinh lúc cài đặt, không đổi qua
  các lần cập nhật, và không có giao diện nào cho phép sửa.
- Tên máy và mã bộ xử lý — hai lớp phụ, giúp phân biệt hai máy nhân bản từ
  cùng một ảnh đĩa (trường hợp GUID trùng nhau).

Kết quả là chuỗi SHA-256 64 ký tự. Cài lại ứng dụng, xóa ``.env``, đổi thư
mục — mã vẫn thế, nên credit đã mua không mất. Cài lại Windows thì GUID mới,
mã mới: trường hợp đó người dùng liên hệ hỗ trợ để chuyển credit sang máy.
"""
from __future__ import annotations

import hashlib
import platform
import uuid

_cached_fingerprint: str | None = None


def _machine_guid() -> str:
    """MachineGuid của Windows; địa chỉ MAC là phương án dự phòng."""
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            # Bắt buộc đọc nhánh 64-bit: tiến trình 32-bit bị chuyển hướng
            # sang Wow6432Node và đọc ra GUID KHÁC — mã thiết bị sẽ đổi chỉ
            # vì đổi kiến trúc bản đóng gói.
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        )
        try:
            guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            return str(guid).strip()
        finally:
            winreg.CloseKey(key)
    except (ImportError, OSError):
        # Không phải Windows, hoặc registry không đọc được: dùng địa chỉ MAC.
        # Kém ổn định hơn (card mạng ảo có thể đổi) nhưng còn hơn không có gì.
        return f"mac-{uuid.getnode():012x}"


def get_fingerprint() -> str:
    """Mã thiết bị (SHA-256 hex, 64 ký tự). Tính một lần mỗi phiên."""
    global _cached_fingerprint
    if _cached_fingerprint is not None:
        return _cached_fingerprint

    raw = "|".join((
        _machine_guid(),
        platform.node(),
        platform.machine(),
    ))
    _cached_fingerprint = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return _cached_fingerprint


def get_device_name() -> str:
    """Tên máy hiển thị trong trang quản trị, vd "DESKTOP-ABC (Windows 10.0.26200)"."""
    node = platform.node() or "Máy không tên"
    system = platform.system() or "?"
    release = platform.version() or platform.release() or ""
    return f"{node} ({system} {release})".strip()


def short_id() -> str:
    """8 ký tự đầu của mã thiết bị — đủ để đọc cho bộ phận hỗ trợ."""
    return get_fingerprint()[:8].upper()
