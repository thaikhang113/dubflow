"""Kiểm tra máy chủ lúc khởi động: bảo trì, phiên bản, phiên thiết bị.

Máy chủ dịch là TÙY CHỌN. Chưa cấu hình ``VOXDUB_API_URL`` thì bỏ qua toàn bộ
phần kiểm tra này và vào thẳng app — mọi việc chạy trên máy (nghe-chép, lồng
tiếng, phụ đề, xuất video) đều dùng được, riêng bước dịch chuyển sang dịch
tay.

Đã cấu hình máy chủ rồi thì làm ba việc, theo đúng thứ tự quan trọng:

1. **Liên lạc được máy chủ** — KHÔNG hỏi được thì không vào (fail-closed).
   Đã trỏ về một máy chủ mà máy chủ đó im lặng thì chạy tiếp chỉ tạo cảm giác
   hỏng ngẫu nhiên ở bước dịch.
2. **Bảo trì** — máy chủ báo đang bảo trì thì chặn hẳn, kèm lời nhắn của
   quản trị.
3. **Phiên bản tối thiểu** — bản app quá cũ (API đã đổi) thì buộc cập nhật.

Đăng ký thiết bị (bước cuối) hỏng thì KHÔNG chặn: máy chủ sống là đủ điều
kiện vào; số dư sẽ tự đồng bộ ở lần gọi sau.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StartupResult:
    """Kết quả kiểm tra khởi động."""

    #: False = chặn hẳn, hiện ``message`` rồi thoát.
    allowed: bool = True
    message: str = ""
    #: True khi lý do chặn là app quá cũ (giao diện mời tải bản mới).
    needs_update: bool = False
    #: Cấu hình máy chủ trả về (bảng giá, cờ tính năng). Rỗng khi mất mạng.
    config: dict = field(default_factory=dict)
    #: Thông tin thiết bị + số dư. Rỗng khi chưa đăng ký được.
    device: dict = field(default_factory=dict)
    #: True khi không kết nối được máy chủ — lý do chặn ĐÁNG THỬ LẠI
    #: (giao diện hiện nút "Thử lại" thay vì chỉ có "Thoát").
    offline: bool = False
    #: True khi chạy thuần trên máy (chưa cấu hình máy chủ dịch). Giao diện
    #: ẩn huy hiệu Vox và trang Tài khoản.
    local_only: bool = False


def _version_tuple(text: str) -> tuple[int, ...]:
    """"3.0.1" → (3, 0, 1, 0). Phần không phải số bị bỏ qua (vd "3.1-beta").

    Đệm số 0 cho đủ 4 phần để "3.0" không bị coi là CŨ HƠN "3.0.0"
    ((3, 0) < (3, 0, 0) theo luật so tuple của Python).
    """
    parts = []
    for chunk in str(text or "").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts)


def check_startup(app_version: str) -> StartupResult:
    """Hỏi máy chủ xem app có được phép chạy không. Gọi trên luồng nền."""
    from autodub.saas_client import SaasError, get_client, is_configured

    if not is_configured():
        # Chạy thuần trên máy: không có máy chủ để hỏi, và cũng không cần.
        return StartupResult(local_only=True,
                             config={"creditEnabled": False})

    client = get_client()
    config = client.app_config(force=True)
    if not config:
        # Fail-closed: không hỏi được máy chủ thì không vào. offline=True
        # để giao diện biết đây là lỗi đáng thử lại chứ không phải bị cấm.
        return StartupResult(
            allowed=False,
            offline=True,
            message=(
                "Không kết nối được máy chủ VoxDub.\n\n"
                "Kiểm tra mạng rồi bấm Thử lại. Nếu mạng bình thường thì "
                "máy chủ đang khởi động lại — chờ một lát."))

    if config.get("maintenanceMode"):
        return StartupResult(
            allowed=False,
            message=str(config.get("maintenanceMessage") or "").strip()
            or "Hệ thống đang bảo trì. Vui lòng quay lại sau ít phút.",
            config=config)

    current = _version_tuple(app_version)
    minimum = str(config.get("minAppVersion") or "")
    forced = str(config.get("forceUpdateVersion") or "")
    required = max((_version_tuple(v) for v in (minimum, forced) if v),
                   default=(0,))
    if current < required:
        return StartupResult(
            allowed=False,
            needs_update=True,
            message=(
                f"Phiên bản {app_version} đã quá cũ và không còn kết nối được "
                f"máy chủ.\n\nHãy tải bản {minimum or forced} trở lên rồi mở "
                "lại ứng dụng."),
            config=config)

    device: dict = {}
    offline = False
    try:
        device = client.ensure_session()
    except SaasError:
        # Đăng ký thiết bị hỏng không phải lý do để chặn: app vẫn dùng được
        # cho mọi việc chạy trên máy (sửa phụ đề, xuất lại, tải video).
        offline = True

    return StartupResult(config=config, device=device, offline=offline)
