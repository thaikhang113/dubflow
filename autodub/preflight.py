"""Kiểm tra "tiền chuyến bay" — máy đã đủ điều kiện chạy lồng tiếng chưa.

Chạy một lượt các kiểm tra rẻ (không nạp model, không chạm mạng) và trả về
danh sách kết quả kèm lời khuyên tiếng Việt. Ba mức:

- ``fail``: thiếu thứ bắt buộc — chạy pipeline chắc chắn hỏng.
- ``warn``: chạy được nhưng dễ gặp trục trặc (đĩa gần đầy, RAM thấp...).
- ``ok``:   đạt.

Không import Qt — GUI bọc lại trong worker riêng, CLI/pytest gọi thẳng.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass

from autodub.config import Settings
from autodub.utils import app_root

#: Đĩa trống tối thiểu (GB). Một video 30 phút cần ~5-8 GB tệp trung gian
#: (WAV tách nhạc, từng đoạn TTS, video xuất) nên dưới 2 GB coi như chặn.
DISK_FAIL_GB = 2.0
DISK_WARN_GB = 10.0

#: RAM tối thiểu (GB). Demucs + Whisper CPU cần ~6 GB lúc cao điểm.
RAM_WARN_GB = 8.0

_SUBPROCESS_TIMEOUT = 15


@dataclass(frozen=True)
class CheckResult:
    """Kết quả một mục kiểm tra, đủ chữ để hiện thẳng lên giao diện."""

    key: str            # định danh máy đọc: "ffmpeg", "disk", ...
    title: str          # tên mục ngắn gọn cho người dùng
    level: str          # "ok" | "warn" | "fail"
    message: str        # tình trạng hiện tại
    advice: str = ""    # cách khắc phục (rỗng khi ok)

    @property
    def ok(self) -> bool:
        return self.level == "ok"


def run_preflight(settings: Settings | None = None) -> list[CheckResult]:
    """Chạy toàn bộ kiểm tra; không bao giờ ném lỗi ra ngoài."""
    if settings is None:
        settings = Settings.load()
    checks = (
        _check_ffmpeg,
        _check_ffprobe,
        lambda s: _check_disk(s),
        lambda s: _check_ram(s),
        _check_vieneu,
        _check_asr,
    )
    results: list[CheckResult] = []
    for check in checks:
        try:
            results.append(check(settings))
        except Exception as e:  # noqa: BLE001 — một mục hỏng không chặn các mục khác
            results.append(CheckResult(
                key="internal", title="Kiểm tra hệ thống", level="warn",
                message=f"Một mục kiểm tra bị lỗi: {e}",
                advice="Bỏ qua được; nếu ứng dụng chạy sai, hãy gửi tệp log "
                       "cho người hỗ trợ."))
    return results


def blocking_failures(results: list[CheckResult]) -> list[CheckResult]:
    """Các mục ``fail`` — thiếu thì pipeline không chạy nổi."""
    return [r for r in results if r.level == "fail"]


def warnings_of(results: list[CheckResult]) -> list[CheckResult]:
    return [r for r in results if r.level == "warn"]


# --------------------------------------------------------------------------- #
# Từng mục kiểm tra
# --------------------------------------------------------------------------- #

def _check_ffmpeg(settings: Settings) -> CheckResult:
    """FFmpeg có mặt và có bộ lọc phụ đề (libass) không."""
    title = "FFmpeg"
    # Kiểm tra cả thư mục bin/ cục bộ (tải bởi wizard) lẫn PATH hệ thống
    local_ffmpeg = os.path.join(app_root(), "bin", "ffmpeg.exe")
    ffmpeg_cmd = shutil.which("ffmpeg") or (
        local_ffmpeg if os.path.isfile(local_ffmpeg) else None)
    if not ffmpeg_cmd:
        return CheckResult(
            key="ffmpeg", title=title, level="fail",
            message="Máy chưa có FFmpeg.",
            advice="Tải bản đầy đủ (full build) từ gyan.dev hoặc BtbN, giải "
                   "nén rồi thêm thư mục bin vào đường dẫn hệ thống (PATH), "
                   "sau đó mở lại ứng dụng.")
    try:
        out = subprocess.run(
            [ffmpeg_cmd, "-hide_banner", "-filters"],
            capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        out = ""
    # Bản "essentials" thiếu libass → thiếu bộ lọc subtitles → phụ đề ghi
    # vào hình sẽ hỏng dù mọi thứ khác chạy bình thường.
    if " subtitles " not in out:
        return CheckResult(
            key="ffmpeg", title=title, level="warn",
            message="FFmpeg đang cài là bản rút gọn, thiếu bộ ghi phụ đề "
                    "(libass).",
            advice="Thay bằng bản đầy đủ (full build): tải từ gyan.dev "
                   "(gói ffmpeg-release-full), giải nén đè lên bản cũ hoặc "
                   "cập nhật PATH trỏ tới bản mới.")
    return CheckResult(key="ffmpeg", title=title, level="ok",
                       message="Bản đầy đủ, có bộ ghi phụ đề.")


def _check_ffprobe(settings: Settings) -> CheckResult:
    """ffprobe — đọc thời lượng/thông số video, đi kèm gói FFmpeg."""
    if shutil.which("ffprobe"):
        return CheckResult(key="ffprobe", title="FFprobe", level="ok",
                           message="Sẵn sàng.")
    return CheckResult(
        key="ffprobe", title="FFprobe", level="fail",
        message="Máy có thể thiếu ffprobe (thường nằm cùng thư mục với "
                "ffmpeg).",
        advice="Cài lại FFmpeg bản đầy đủ — ffprobe nằm sẵn trong cùng thư "
               "mục bin.")


def _check_disk(settings: Settings) -> CheckResult:
    """Đĩa trống ở nơi ghi kết quả (OUTPUT_DIR, cùng ổ với thư mục app)."""
    target = settings.output_dir or app_root()
    # Thư mục có thể chưa tồn tại (lần chạy đầu) — đo ổ đĩa cha gần nhất.
    probe = target
    while probe and not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    free_gb = shutil.disk_usage(probe).free / (1024 ** 3)
    if free_gb < DISK_FAIL_GB:
        return CheckResult(
            key="disk", title="Dung lượng đĩa", level="fail",
            message=f"Ổ đĩa chứa kết quả chỉ còn {free_gb:.1f} GB trống.",
            advice="Dọn bớt tệp trên ổ đĩa này (cần tối thiểu "
                   f"{DISK_FAIL_GB:.0f} GB, khuyến nghị {DISK_WARN_GB:.0f} GB) "
                   "hoặc đổi Thư mục kết quả trong Cài đặt sang ổ khác.")
    if free_gb < DISK_WARN_GB:
        return CheckResult(
            key="disk", title="Dung lượng đĩa", level="warn",
            message=f"Ổ đĩa chứa kết quả còn {free_gb:.1f} GB trống — video "
                    "dài có thể không đủ chỗ.",
            advice=f"Nên giữ ít nhất {DISK_WARN_GB:.0f} GB trống, hoặc đổi "
                   "Thư mục kết quả trong Cài đặt sang ổ khác.")
    return CheckResult(key="disk", title="Dung lượng đĩa", level="ok",
                       message=f"Còn {free_gb:.0f} GB trống.")


def _total_ram_gb() -> float:
    """Tổng RAM (GB); 0.0 nếu không đọc được (không chặn ai cả)."""
    if sys.platform == "win32":
        import ctypes

        class _MemStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_uint32),
                        ("dwMemoryLoad", ctypes.c_uint32),
                        ("ullTotalPhys", ctypes.c_uint64),
                        ("ullAvailPhys", ctypes.c_uint64),
                        ("ullTotalPageFile", ctypes.c_uint64),
                        ("ullAvailPageFile", ctypes.c_uint64),
                        ("ullTotalVirtual", ctypes.c_uint64),
                        ("ullAvailVirtual", ctypes.c_uint64),
                        ("ullAvailExtendedVirtual", ctypes.c_uint64)]

        status = _MemStatus()
        status.dwLength = ctypes.sizeof(_MemStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.ullTotalPhys / (1024 ** 3)
        return 0.0
    try:
        page = os.sysconf("SC_PAGE_SIZE")
        count = os.sysconf("SC_PHYS_PAGES")
        return page * count / (1024 ** 3)
    except (ValueError, OSError, AttributeError):
        return 0.0


def _check_ram(settings: Settings) -> CheckResult:
    total = _total_ram_gb()
    if total <= 0:
        return CheckResult(key="ram", title="Bộ nhớ RAM", level="ok",
                           message="Không đọc được thông số — bỏ qua.")
    if total < RAM_WARN_GB:
        return CheckResult(
            key="ram", title="Bộ nhớ RAM", level="warn",
            message=f"Máy có {total:.0f} GB RAM — dưới mức khuyến nghị "
                    f"{RAM_WARN_GB:.0f} GB.",
            advice="Vẫn chạy được nhưng nên đóng bớt ứng dụng khác khi lồng "
                   "tiếng, và trong Cài đặt giảm số luồng giọng đọc xuống 1.")
    return CheckResult(key="ram", title="Bộ nhớ RAM", level="ok",
                       message=f"{total:.0f} GB.")


def _check_vieneu(settings: Settings) -> CheckResult:
    """Bộ giọng VieNeu — chỉ cần cho giọng offline, không phải cho cả app."""
    if settings.vieneu_configured():
        return CheckResult(key="vieneu", title="Bộ giọng đọc VieNeu",
                           level="ok", message="Đã cài.")
    # Không còn là lỗi chặn: 22 giọng CapCut chạy qua mạng, không cần model
    # trên máy — chặn ở đây thì máy chưa cài VieNeu không mở nổi ứng dụng.
    return CheckResult(
        key="vieneu", title="Bộ giọng đọc VieNeu", level="warn",
        message="Chưa cài — hiện chỉ dùng được bộ giọng CapCut (cần mạng).",
        advice="Muốn lồng tiếng offline thì mở cửa sổ dòng lệnh tại thư mục "
               "ứng dụng rồi chạy: py scripts/setup_vieneu.py — cài một lần, "
               "khoảng vài phút.")


def _check_asr(settings: Settings) -> CheckResult:
    """Bộ nghe đang chọn trong cấu hình có sẵn sàng không."""
    if settings.asr_engine == "paraformer":
        if settings.paraformer_configured():
            return CheckResult(key="asr", title="Bộ nghe (Paraformer)",
                               level="ok", message="Đã cài.")
        return CheckResult(
            key="asr", title="Bộ nghe (Paraformer)", level="fail",
            message="Cấu hình đang chọn Paraformer nhưng máy chưa cài.",
            advice="Chạy: py scripts/setup_paraformer.py — hoặc trong Cài đặt "
                   "đổi Bộ nghe về Whisper (không cần cài thêm).")
    # Whisper tải model tự động ở lần chạy đầu — chỉ cần xác nhận gói có mặt.
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return CheckResult(
            key="asr", title="Bộ nghe (Whisper)", level="fail",
            message="Thiếu thư viện faster-whisper.",
            advice="Cài lại phụ thuộc: py -m pip install -r requirements.txt "
                   "— hoặc cài lại ứng dụng nếu đang dùng bản đóng gói.")
    # Báo trước khi Whisper tải model lần đầu — tránh người dùng tưởng treo.
    model_name = settings.whisper_model
    model_dir = os.path.join(
        os.path.expanduser("~"), ".cache", "huggingface", "hub")
    # Thư mục cache có thể chứa nhiều model; chỉ kiểm tra model đang chọn.
    model_slug = f"models--Systran--faster-whisper-{model_name}"
    already_cached = os.path.isdir(os.path.join(model_dir, model_slug))
    if not already_cached:
        size_hint = {
            "tiny": "~75 MB", "tiny.en": "~75 MB",
            "base": "~140 MB", "base.en": "~140 MB",
            "small": "~460 MB", "small.en": "~460 MB",
            "medium": "~1.5 GB", "medium.en": "~1.5 GB",
            "large-v1": "~2.9 GB", "large-v2": "~2.9 GB",
            "large-v3": "~2.9 GB", "large": "~2.9 GB",
        }.get(model_name, "~1–3 GB")
        return CheckResult(
            key="asr", title="Bộ nghe (Whisper)", level="warn",
            message=f"Model Whisper '{model_name}' chưa được tải về "
                    f"(lần chạy đầu sẽ tự tải, khoảng {size_hint}).",
            advice=f"Khi bắt đầu lồng tiếng lần đầu, ứng dụng sẽ tải "
                   f"model '{model_name}' ({size_hint}) về máy — chỉ một lần, "
                   "sau đó dùng lại mãi. Nếu muốn nhanh hơn (nhưng kém chính "
                   "xác hơn), đặt WHISPER_MODEL=small trong Cài đặt.")
    return CheckResult(key="asr", title="Bộ nghe (Whisper)", level="ok",
                       message=f"Model '{model_name}' đã có sẵn.")
