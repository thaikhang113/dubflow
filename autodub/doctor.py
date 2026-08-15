"""Kiểm tra và định tuyến sửa lỗi môi trường phát hành DubFlow."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from dataclasses import dataclass

from autodub.config import Settings
from autodub.preflight import CheckResult, run_preflight
from autodub.utils import data_root


@dataclass(frozen=True)
class DoctorCheck:
    key: str
    title: str
    level: str
    message: str
    advice: str = ""
    repair_script: str = ""

    @property
    def repairable(self) -> bool:
        return bool(self.repair_script)


_REPAIR_SCRIPTS = {
    "vieneu": "scripts/setup_vieneu.py",
    "asr": "scripts/setup_paraformer.py",
    "ocr": "scripts/setup_ocr.py",
    "deepseek_ocr": "scripts/setup_deepseek_ocr.py",
    "vsr": "scripts/setup_vsr.py",
    "douyin": "scripts/setup_douyin.py",
    "demucs": "scripts/setup_demucs.py",
    "voices": "scripts/setup_voices.py",
}


def repair_script_for(check_key: str) -> str:
    return _REPAIR_SCRIPTS.get(check_key, "")


def run_doctor(settings: Settings | None = None) -> list[DoctorCheck]:
    """Chạy kiểm tra nhẹ, không tải model và không xóa dữ liệu người dùng."""
    settings = settings or Settings.load()
    results = [_from_preflight(item) for item in run_preflight(settings)]
    results.extend((
        _check_python(),
        _check_import("yt_dlp", "Bộ tải video", "yt_dlp"),
        _check_multimedia(),
        _check_ocr(settings),
        _check_vsr(settings),
        _check_douyin(),
        _check_demucs(),
        _check_voices(settings),
        _check_writable_path("Dữ liệu ứng dụng", data_root()),
        _check_writable_path("Thư mục kết quả", settings.output_dir),
    ))
    if settings.deepseek_ocr_enabled:
        results.append(_check_deepseek_ocr(settings))
    return results


def _from_preflight(item: CheckResult) -> DoctorCheck:
    script = repair_script_for(item.key)
    if item.key in ("ffmpeg", "ffprobe") and os.name == "nt":
        script = "__ffmpeg__"
    if item.key == "asr":
        script = (
            "scripts/setup_paraformer.py"
            if "Paraformer" in item.title
            else "scripts/setup_whisper.py"
        )
    return DoctorCheck(
        key=item.key,
        title=item.title,
        level=item.level,
        message=item.message,
        advice=item.advice,
        repair_script=script,
    )


def _check_python() -> DoctorCheck:
    version = f"{sys.version_info[0]}.{sys.version_info[1]}"
    if (3, 10) <= sys.version_info[:2] <= (3, 12):
        return DoctorCheck("python", "Python runtime", "ok", f"Python {version}.")
    return DoctorCheck(
        "python",
        "Python runtime",
        "fail",
        f"Python {version} không nằm trong dải hỗ trợ 3.10–3.12.",
        "Cài Python 3.12 rồi chạy lại tính năng cài đặt.",
    )


def _check_import(module: str, title: str, key: str) -> DoctorCheck:
    try:
        if importlib.util.find_spec(module) is None:
            raise ImportError
    except Exception:
        return DoctorCheck(
            key,
            title,
            "fail",
            f"Thiếu thư viện {module}.",
            "Cài lại ứng dụng hoặc chạy trình cài đặt phụ thuộc tương ứng.",
        )
    return DoctorCheck(key, title, "ok", "Sẵn sàng.")


def _check_multimedia() -> DoctorCheck:
    try:
        from PySide6.QtMultimedia import QMediaPlayer  # noqa: F401
        from PySide6.QtMultimediaWidgets import QGraphicsVideoItem  # noqa: F401
    except Exception as exc:
        return DoctorCheck(
            "multimedia",
            "Phát video",
            "fail",
            "Không nạp được thành phần phát video.",
            f"Mở lại ứng dụng sau khi cài lại PySide6. Chi tiết: {exc}",
        )
    return DoctorCheck("multimedia", "Phát video", "ok", "Sẵn sàng.")


def _check_ocr(settings: Settings) -> DoctorCheck:
    if not settings.ocr_enabled:
        return DoctorCheck("ocr", "PaddleOCR", "warn", "Đã tắt OCR trong Cài đặt.")
    return _check_optional_component(
        key="ocr",
        title="PaddleOCR",
        enabled=True,
        configured=settings.ocr_configured(),
        script=repair_script_for("ocr"),
    )


def _check_deepseek_ocr(settings: Settings) -> DoctorCheck:
    if not settings.deepseek_ocr_configured():
        return _check_optional_component(
            key="deepseek_ocr",
            title="DeepSeek-OCR",
            enabled=True,
            configured=False,
            script=repair_script_for("deepseek_ocr"),
        )
    marker = os.path.join(
        settings.deepseek_ocr_model_dir_path(), "installed_ok.json"
    )
    try:
        with open(marker, encoding="utf-8") as handle:
            backend = str(json.load(handle).get("device_backend", "")).lower()
    except (OSError, ValueError):
        backend = ""
    labels = {
        "cuda": "NVIDIA CUDA",
        "rocm": "AMD ROCm",
        "directml": "AMD DirectML",
    }
    if backend not in labels:
        return DoctorCheck(
            "deepseek_ocr",
            "DeepSeek-OCR",
            "fail",
            "DeepSeek-OCR thiếu backend GPU trong marker.",
            "Bấm Tải lại để cài lại backend GPU.",
            repair_script_for("deepseek_ocr"),
        )
    return DoctorCheck(
        "deepseek_ocr",
        "DeepSeek-OCR",
        "ok",
        f"Đã cài với {labels[backend]}.",
    )


def _check_vsr(settings: Settings) -> DoctorCheck:
    if not settings.vsr_enabled:
        return DoctorCheck("vsr", "AI xóa phụ đề", "warn",
                           "Đã tắt trong Cài đặt.")
    if settings.vsr_configured():
        return DoctorCheck("vsr", "AI xóa phụ đề", "ok",
                           f"Đã cài, mode {settings.vsr_mode}.")
    return DoctorCheck(
        "vsr",
        "AI xóa phụ đề",
        "fail",
        "VSR chưa sẵn sàng.",
        "Bấm Tải lại để tải engine và model cần thiết.",
        repair_script_for("vsr"),
    )


def _check_optional_component(
    *, key: str, title: str, enabled: bool, configured: bool, script: str
) -> DoctorCheck:
    if not enabled:
        return DoctorCheck(key, title, "warn", "Đã tắt trong Cài đặt.")
    if configured:
        return DoctorCheck(key, title, "ok", "Đã cài và có marker smoke test.")
    return DoctorCheck(
        key,
        title,
        "fail",
        f"{title} chưa sẵn sàng.",
        f"Bấm Tải lại để chạy {os.path.basename(script)}.",
        script,
    )


def _check_douyin() -> DoctorCheck:
    try:
        if importlib.util.find_spec("playwright") is None:
            raise ImportError
    except Exception:
        return DoctorCheck(
            "douyin",
            "Tải Douyin",
            "fail",
            "Thiếu Playwright/Chromium cho đường tải dự phòng Douyin.",
            "Bấm Tải lại để cài Playwright và Chromium.",
            repair_script_for("douyin"),
        )
    return DoctorCheck("douyin", "Tải Douyin", "ok", "Playwright đã sẵn sàng.")


def _check_demucs() -> DoctorCheck:
    marker = os.path.join(data_root(), "models", "demucs", "installed_ok.json")
    if os.path.isfile(marker):
        return DoctorCheck("demucs", "Tách giọng nền", "ok", "Đã cài.")
    return DoctorCheck(
        "demucs",
        "Tách giọng nền",
        "warn",
        "Demucs chưa cài; chỉ cần khi tách giọng và giữ nhạc nền.",
        "Bấm Tải lại nếu muốn dùng tách giọng nền.",
        repair_script_for("demucs"),
    )


def _check_voices(settings: Settings) -> DoctorCheck:
    try:
        from autodub.speech.tts import voice_library

        total, todo = voice_library.summary(settings)
    except Exception:
        total, todo = 0, 0
    if total and not todo:
        return DoctorCheck("voices", "Thư viện giọng", "ok", f"Đã có {total} giọng.")
    return DoctorCheck(
        "voices",
        "Thư viện giọng",
        "warn",
        "Thư viện giọng mẫu chưa nạp đủ.",
        "Bấm Tải lại để nạp các giọng còn thiếu.",
        repair_script_for("voices"),
    )


def _check_writable_path(title: str, path: str) -> DoctorCheck:
    candidate = os.path.abspath(os.path.expanduser(path or data_root()))
    probe = candidate
    while not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            return DoctorCheck(
                f"writable:{title}",
                title,
                "fail",
                "Không tìm được thư mục cha để ghi.",
                "Chọn lại thư mục trong Cài đặt.",
            )
        probe = parent
    if not os.access(probe, os.W_OK):
        return DoctorCheck(
            f"writable:{title}",
            title,
            "fail",
            "Thư mục hiện tại không cho phép ghi.",
            "Chọn thư mục khác có quyền ghi.",
        )
    return DoctorCheck(f"writable:{title}", title, "ok", "Có quyền ghi.")
