"""Optional external Video2X post-render upscaler."""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Video2XResult:
    output_path: str
    used_video2x: bool
    error: str = ""


def build_video2x_command(
    binary: str,
    input_path: str,
    output_path: str,
    *,
    profile: str = "realesrgan",
    scale: int = 2,
    model: str = "",
) -> list[str]:
    command = [
        binary, "-i", input_path, "-o", output_path,
        "-p", profile, "-s", str(max(2, min(4, int(scale)))),
    ]
    if profile == "realesrgan" and model:
        command += ["--realesrgan-model", model]
    return command


def run_video2x_or_fallback(
    input_path: str,
    output_path: str,
    *,
    command: list[str],
    run_command: Callable[[list[str]], object] | None = None,
) -> Video2XResult:
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Video2X input not found: {input_path}")
    try:
        runner = run_command or (
            lambda cmd: subprocess.run(
                cmd, check=True, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
        )
        runner(command)
        if not os.path.isfile(output_path) or os.path.getsize(output_path) <= 0:
            raise RuntimeError("Video2X không tạo được file đầu ra.")
        return Video2XResult(output_path, True)
    except Exception as exc:  # noqa: BLE001 - optional stage must not lose render
        try:
            if os.path.isfile(output_path):
                os.remove(output_path)
        except OSError:
            pass
        return Video2XResult(input_path, False, str(exc))


def upscale_video_or_fallback(
    input_path: str,
    settings,
    *,
    output_path: str | None = None,
) -> Video2XResult:
    if not getattr(settings, "video2x_enabled", False):
        return Video2XResult(input_path, False, "Video2X đã tắt.")
    binary = getattr(settings, "video2x_binary", "") or shutil.which("video2x")
    if not binary:
        return Video2XResult(input_path, False, "Không tìm thấy binary Video2X.")
    output = output_path or input_path + ".video2x.mp4"
    command = build_video2x_command(
        binary, input_path, output,
        profile=getattr(settings, "video2x_profile", "realesrgan"),
        scale=getattr(settings, "video2x_scale", 2),
        model=getattr(settings, "video2x_model", ""),
    )
    return run_video2x_or_fallback(input_path, output, command=command)
