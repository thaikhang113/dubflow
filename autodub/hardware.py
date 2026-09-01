"""Lightweight hardware detection and deterministic backend selection."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass

CommandRunner = Callable[..., object]


@dataclass(frozen=True)
class HardwareProfile:
    platform: str
    machine: str
    python: str
    ram_gb: float
    disk_free_gb: float
    gpu_vendor: str = ""
    gpu_name: str = ""
    nvidia: bool = False
    amd: bool = False
    rocm: bool = False
    directml: bool = False
    vulkan: bool = False

    def as_dict(self) -> dict:
        return {
            "platform": self.platform,
            "machine": self.machine,
            "python": self.python,
            "ram_gb": self.ram_gb,
            "disk_free_gb": self.disk_free_gb,
            "gpu_vendor": self.gpu_vendor,
            "gpu_name": self.gpu_name,
            "nvidia": self.nvidia,
            "amd": self.amd,
            "rocm": self.rocm,
            "directml": self.directml,
            "vulkan": self.vulkan,
        }


@dataclass(frozen=True)
class BackendPlan:
    ocr_backend: str
    vsr_backend: str
    reasons: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "ocr_backend": self.ocr_backend,
            "vsr_backend": self.vsr_backend,
            "reasons": list(self.reasons),
        }


def _run(command: list[str], runner: CommandRunner) -> tuple[bool, str]:
    try:
        result = runner(
            command,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False, ""
    output = f"{getattr(result, 'stdout', '')}\n{getattr(result, 'stderr', '')}"
    return getattr(result, "returncode", 1) == 0, output.strip()


def _ram_gb(runner: CommandRunner) -> float:
    try:
        with open("/proc/meminfo", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    return round(int(line.split()[1]) / 1024 / 1024, 1)
    except (OSError, ValueError):
        pass
    ok, output = _run(
        [
            "powershell", "-NoProfile", "-Command",
            "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory",
        ],
        runner,
    )
    if ok:
        try:
            return round(int(output.splitlines()[0]) / 1024**3, 1)
        except (ValueError, IndexError):
            pass
    return 0.0


def detect_hardware(
    *,
    runner: CommandRunner = subprocess.run,
    disk_path: str | None = None,
    platform_name: str | None = None,
) -> HardwareProfile:
    platform_name = platform_name or sys.platform
    machine = platform.machine()
    nvidia, nvidia_text = _run(["nvidia-smi", "-L"], runner)
    gpu_text = nvidia_text
    if platform_name == "win32":
        _, windows_text = _run(
            [
                "powershell", "-NoProfile", "-Command",
                "(Get-CimInstance Win32_VideoController).Name",
            ],
            runner,
        )
        gpu_text = f"{gpu_text}\n{windows_text}".strip()
    else:
        _, lspci_text = _run(["lspci"], runner)
        gpu_text = f"{gpu_text}\n{lspci_text}".strip()
    lower = gpu_text.lower()
    amd = any(token in lower for token in ("amd", "ati", "radeon"))
    vulkan, _ = _run(["vulkaninfo", "--summary"], runner)
    rocm, _ = _run(["rocminfo"], runner)
    directml = platform_name == "win32" and (amd or nvidia or "intel" in lower)
    vendor = "nvidia" if nvidia else "amd" if amd else ""
    name = next(
        (line.strip() for line in gpu_text.splitlines() if line.strip()),
        "",
    )
    disk_root = os.path.abspath(disk_path or os.getcwd())
    while not os.path.exists(disk_root):
        parent = os.path.dirname(disk_root)
        if parent == disk_root:
            disk_root = os.getcwd()
            break
        disk_root = parent
    usage = shutil.disk_usage(disk_root)
    return HardwareProfile(
        platform=platform_name,
        machine=machine,
        python=f"{sys.version_info[0]}.{sys.version_info[1]}",
        ram_gb=_ram_gb(runner),
        disk_free_gb=round(usage.free / 1024**3, 1),
        gpu_vendor=vendor,
        gpu_name=name,
        nvidia=nvidia,
        amd=amd,
        rocm=rocm,
        directml=directml,
        vulkan=vulkan,
    )


def select_backends(
    profile: HardwareProfile, deepseek_ocr_enabled: bool | None = None
) -> BackendPlan:
    reasons: list[str] = []
    if deepseek_ocr_enabled is None:
        deepseek_ocr_enabled = os.environ.get(
            "DEEPSEEK_OCR_ENABLED", "false").strip().lower() in (
                "1", "true", "yes", "on")
    enough_ram = profile.ram_gb == 0 or profile.ram_gb >= 8
    if deepseek_ocr_enabled and profile.nvidia and enough_ram:
        ocr = "deepseek-cuda"
        reasons.append("NVIDIA CUDA và RAM phù hợp cho DeepSeek-OCR.")
    elif deepseek_ocr_enabled and profile.amd and profile.rocm and enough_ram:
        ocr = "deepseek-rocm"
        reasons.append("AMD ROCm và RAM phù hợp cho DeepSeek-OCR.")
    elif (deepseek_ocr_enabled and profile.platform == "win32"
          and profile.directml and enough_ram):
        ocr = "deepseek-directml"
        reasons.append("DirectML khả dụng trên Windows.")
    else:
        ocr = "paddleocr"
        reasons.append("Dùng PaddleOCR CPU tương thích rộng.")

    if enough_ram and profile.disk_free_gb >= 4:
        vsr = "video-subtitle-remover"
        reasons.append("RAM và disk đủ cho VSR.")
    else:
        vsr = "fallback"
        reasons.append("Dùng blur/box fallback để giảm tải tài nguyên.")
    return BackendPlan(ocr, vsr, tuple(reasons))
