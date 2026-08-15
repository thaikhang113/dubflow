from __future__ import annotations

import subprocess

import pytest

from autodub.media.vsr import (
    build_vsr_command,
    normalize_vsr_regions,
    run_vsr_or_fallback,
)


def test_normalize_vsr_regions_uses_ymin_ymax_xmin_xmax():
    result = normalize_vsr_regions([
        {"x": 0.1, "y": 0.7, "w": 0.8, "h": 0.2},
        {"x": 0.0, "y": 0.9, "w": 0.2, "h": 0.2},
    ])

    assert result == [(0.7, 0.9, 0.1, 0.9), (0.9, 1.0, 0.0, 0.2)]


def test_build_vsr_command_passes_regions_and_mode():
    command = build_vsr_command(
        "python",
        "worker.py",
        "in.mp4",
        "out.mp4",
        [{"x": 0.1, "y": 0.7, "w": 0.8, "h": 0.2}],
        mode="sttn-det",
    )

    assert command[:4] == ["python", "worker.py", "--input", "in.mp4"]
    assert "--output" in command
    assert "--inpaint-mode" in command
    assert "sttn-det" in command
    assert "--subtitle-area-coords" in command
    assert command[-4:] == ["0.7", "0.9", "0.1", "0.9"]


def test_vsr_failure_returns_fallback_result(tmp_path):
    source = tmp_path / "source.mp4"
    fallback = tmp_path / "fallback.mp4"
    source.write_bytes(b"source")
    fallback.write_bytes(b"fallback")

    def fail(_command):
        raise subprocess.CalledProcessError(1, ["worker"])

    result = run_vsr_or_fallback(
        str(source),
        str(tmp_path / "vsr.mp4"),
        [{"x": 0.1, "y": 0.7, "w": 0.8, "h": 0.2}],
        run_command=fail,
        fallback=lambda: str(fallback),
    )

    assert result.used_vsr is False
    assert result.output_path == str(fallback)
    assert "worker" in result.error
