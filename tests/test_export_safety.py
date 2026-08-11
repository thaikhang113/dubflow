import json

import pytest

from autodub.media import video


def test_validate_export_part_requires_video_and_audio(tmp_path, monkeypatch):
    part = tmp_path / "dubbed_video.mp4.part"
    part.write_bytes(b"encoded")

    class ProbeResult:
        returncode = 0
        stdout = json.dumps({
            "format": {"duration": "182.4"},
            "streams": [
                {"codec_type": "video"},
                {"codec_type": "audio"},
            ],
        })
        stderr = ""

    monkeypatch.setattr(video.subprocess, "run", lambda *args, **kwargs: ProbeResult())

    info = video.validate_export_part(str(part), expected_duration=180.0)

    assert info["duration"] == pytest.approx(182.4)
    assert info["has_video"] is True
    assert info["has_audio"] is True


def test_replace_output_retries_locked_destination_and_keeps_part(tmp_path, monkeypatch):
    part = tmp_path / "dubbed_video.mp4.part"
    output = tmp_path / "dubbed_video.mp4"
    part.write_bytes(b"new")
    output.write_bytes(b"old")
    calls = []

    def locked_replace(src, dst):
        calls.append((src, dst))
        raise PermissionError(32, "file is locked")

    monkeypatch.setattr(video.os, "replace", locked_replace)
    monkeypatch.setattr(video.time, "sleep", lambda _seconds: None)

    with pytest.raises(video.ExportCommitError, match="đang được ứng dụng khác mở"):
        video.replace_output_with_retry(str(part), str(output), attempts=3)

    assert len(calls) == 3
    assert part.read_bytes() == b"new"
    assert output.read_bytes() == b"old"
