"""Small, side-effect-free hardware backend probe."""
from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass

CommandRunner = Callable[[list[str]], tuple[int, str]]


@dataclass(frozen=True)
class GPUInfo:
    vendor: str = "unknown"
    name: str = ""
    compute_backend: str = "cpu"
    compute_available: bool = False
    reason: str = ""

    @property
    def label(self) -> str:
        name = self.name or self.vendor.upper()
        if self.compute_available:
            return f"{name} ({self.compute_backend})"
        return f"{name} (CPU fallback)"


def _run(command: list[str]) -> tuple[int, str]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return result.returncode, result.stdout or ""


def _first_name(text: str) -> str:
    candidates = []
    for line in text.splitlines():
        line = line.strip()
        if line and "name" not in line.lower():
            candidates.append(line)
    for line in candidates:
        if _vendor(line) != "unknown":
            return line
    return candidates[0] if candidates else ""


def _vendor(name: str) -> str:
    value = name.lower()
    if "amd" in value or "ati" in value or "radeon" in value:
        return "amd"
    if "nvidia" in value or "geforce" in value or "quadro" in value:
        return "nvidia"
    if "intel" in value or "arc" in value:
        return "intel"
    return "unknown"


def detect_gpu(
    *,
    platform_name: str | None = None,
    command_runner: CommandRunner | None = None,
) -> GPUInfo:
    """Detect GPU vendor and a usable compute backend.

    Detection never raises and never claims GPU compute from a vendor name
    alone. A runtime probe must succeed before ``compute_available`` is true.
    """
    platform_name = platform_name or sys.platform
    run = command_runner or _run
    env_vendor = os.environ.get("DUBFLOW_GPU_VENDOR", "").strip().lower()

    if platform_name == "win32":
        code, output = run([
            "powershell", "-NoProfile", "-Command",
            "(Get-CimInstance Win32_VideoController).Name",
        ])
        name = _first_name(output) if code == 0 else ""
        vendor = _vendor(name)
        if vendor == "unknown" and env_vendor:
            vendor = env_vendor
        if vendor == "amd":
            dml_code, dml_output = run([
                sys.executable, "-c",
                "import onnxruntime as o; print('DmlExecutionProvider' "
                "in o.get_available_providers())",
            ])
            if dml_code == 0 and "true" in dml_output.lower():
                return GPUInfo("amd", name, "directml", True, "DirectML ready")
            return GPUInfo("amd", name, "cpu", False,
                           "AMD detected; DirectML runtime unavailable")
        if vendor == "nvidia":
            code, _ = run(["nvidia-smi", "-L"])
            return GPUInfo("nvidia", name, "cuda", code == 0,
                           "CUDA probe" if code == 0 else "CUDA unavailable")
        return GPUInfo(vendor, name, "cpu", False, "No supported compute runtime")

    code, output = run(["lspci"])
    name = _first_name(output) if code == 0 else ""
    vendor = _vendor(name)
    if vendor == "unknown" and env_vendor:
        vendor = env_vendor
    if vendor == "amd":
        code, _ = run(["rocminfo"])
        return GPUInfo("amd", name, "rocm", code == 0,
                       "ROCm probe" if code == 0 else "ROCm unavailable")
    if vendor == "nvidia":
        code, _ = run(["nvidia-smi", "-L"])
        return GPUInfo("nvidia", name, "cuda", code == 0,
                       "CUDA probe" if code == 0 else "CUDA unavailable")
    return GPUInfo(vendor, name, "cpu", False, "No supported compute runtime")
