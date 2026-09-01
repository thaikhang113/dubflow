"""Adapter for the optional video-subtitle-remover backend."""
from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

VSR_MODE = "sttn-det"

def _planned_vsr_backend() -> str:
    path = os.environ.get("DUBFLOW_BACKEND_PLAN", "")
    try:
        with open(path, encoding="utf-8") as handle:
            return str(json.load(handle).get("vsr_backend", ""))
    except (OSError, ValueError, TypeError):
        return ""


@dataclass(frozen=True)
class VSRResult:
    output_path: str
    used_vsr: bool
    error: str = ""


def normalize_vsr_regions(regions: list[dict]) -> list[tuple[float, float, float, float]]:
    output = []
    for region in regions:
        x = max(0.0, min(1.0, float(region.get("x", 0.0))))
        y = max(0.0, min(1.0, float(region.get("y", 0.0))))
        w = max(0.0, min(1.0 - x, float(region.get("w", 0.0))))
        h = max(0.0, min(1.0 - y, float(region.get("h", 0.0))))
        if w and h:
            output.append(tuple(round(value, 6)
                               for value in (y, y + h, x, x + w)))
    return output


def build_vsr_command(
    python_path: str,
    worker_script: str,
    input_path: str,
    output_path: str,
    regions: list[dict],
    *,
    mode: str = VSR_MODE,
) -> list[str]:
    command = [
        python_path,
        worker_script,
        "--input",
        input_path,
        "--output",
        output_path,
        "--inpaint-mode",
        mode,
    ]
    coords = normalize_vsr_regions(regions)
    if coords:
        command += ["--subtitle-area-coords", *[
            f"{value:g}" for value in coords[0]
        ]]
    return command


def run_vsr_or_fallback(
    input_path: str,
    output_path: str,
    regions: list[dict],
    *,
    run_command: Callable[[list[str]], object],
    fallback: Callable[[], str],
    command: list[str] | None = None,
) -> VSRResult:
    if not regions:
        return VSRResult(fallback(), False, "Không có vùng phụ đề OCR.")
    try:
        run_command(command or [])
        if not os.path.isfile(output_path) or os.path.getsize(output_path) <= 0:
            raise RuntimeError("VSR không tạo được video đầu ra.")
        return VSRResult(output_path, True)
    except Exception as exc:
        return VSRResult(fallback(), False, str(exc))


def remove_subtitles(
    input_path: str,
    output_path: str,
    regions: list[dict],
    settings,
    *,
    fallback: Callable[[], str],
) -> VSRResult:
    if not getattr(settings, "vsr_enabled", True):
        return VSRResult(fallback(), False, "VSR đã tắt trong Cài đặt.")
    if _planned_vsr_backend() == "fallback":
        return VSRResult(fallback(), False, "Hardware plan chọn fallback.")
    python_path = settings.vsr_venv_python_path()
    worker_script = settings.vsr_worker_path()
    if not os.path.isfile(python_path) or not os.path.isfile(worker_script):
        return VSRResult(fallback(), False, "VSR chưa được cài.")
    command = build_vsr_command(
        python_path,
        worker_script,
        input_path,
        output_path,
        regions,
        mode=getattr(settings, "vsr_mode", VSR_MODE),
    )
    return run_vsr_or_fallback(
        input_path,
        output_path,
        regions,
        run_command=lambda cmd: subprocess.run(
            cmd, check=True, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            env={
                **os.environ,
                "DUBFLOW_VSR_SOURCE": os.path.join(
                    settings.vsr_model_dir_path(), "source"
                ),
            },
            timeout=max(900, int(_duration_hint(input_path))),
        ),
        fallback=fallback,
        command=command,
    )


def _duration_hint(path: str) -> float:
    try:
        return max(900.0, os.path.getsize(path) / 100_000.0)
    except OSError:
        return 900.0


def subtitle_regions_only(regions: list[dict]) -> list[dict]:
    return [region for region in regions
            if region.get("source") not in ("logo", "branding")]


def union_subtitle_region(regions: list[dict]) -> dict | None:
    regions = subtitle_regions_only(regions)
    if not regions:
        return None
    left = min(float(item.get("x", 0.0)) for item in regions)
    top = min(float(item.get("y", 0.0)) for item in regions)
    right = max(float(item.get("x", 0.0)) + float(item.get("w", 0.0))
                for item in regions)
    bottom = max(float(item.get("y", 0.0)) + float(item.get("h", 0.0))
                 for item in regions)
    return {
        "x": max(0.0, min(1.0, left)),
        "y": max(0.0, min(1.0, top)),
        "w": max(0.0, min(1.0, right) - max(0.0, min(1.0, left))),
        "h": max(0.0, min(1.0, bottom) - max(0.0, min(1.0, top))),
        "source": "ocr",
    }


def copy_without_subtitle_regions(regions: list[dict]) -> list[dict]:
    return [dict(region) for region in regions
            if region.get("source") in ("logo", "branding")]
