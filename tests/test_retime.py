"""Tests for uniform video slow-down (autodub.media.retime).

ffmpeg/ffprobe are stubbed — command shape and the rescale contract are
what matter: setpts factor, cfr pinning, measured-ratio rescale, and the
fail→None fallback of apply_video_speed.
"""
import json
import os

import pytest

from autodub.config import Settings
from autodub.media import retime as retime_mod
from autodub.media.retime import (
    apply_video_speed,
    rescale_blur_regions,
    rescale_segments,
    slow_background,
    slow_video,
)


class Ok:
    returncode = 0
    stdout = ""
    stderr = ""


def seg(i, start, end):
    return {"id": i, "start": start, "end": end, "duration": end - start}


# ------------------------------- rescale ----------------------------------- #

def test_rescale_segments_stretches_timestamps():
    segs = [seg(1, 1.0, 3.0), seg(2, 4.0, 7.0)]
    rescale_segments(segs, 1.25)
    assert segs[0]["start"] == 1.25 and segs[0]["end"] == 3.75
    assert segs[1]["start"] == 5.0 and segs[1]["end"] == 8.75
    assert segs[1]["duration"] == 3.75


def test_rescale_identity():
    segs = [seg(1, 1.0, 3.0)]
    rescale_segments(segs, 1.0)
    assert segs[0]["start"] == 1.0 and segs[0]["end"] == 3.0


def test_rescale_blur_regions():
    regions = [{"x": 0.1, "y": 0.8, "w": 1.0, "h": 0.1,
                "t_start": 2.0, "t_end": 10.0},
               {"x": 0.0, "y": 0.0, "w": 0.5, "h": 0.5}]  # no time window
    out = rescale_blur_regions(regions, 1.2)
    assert out[0]["t_start"] == 2.4 and out[0]["t_end"] == 12.0
    assert "t_start" not in out[1]
    assert regions[0]["t_start"] == 2.0            # input untouched


# ------------------------------- ffmpeg cmds ------------------------------- #

@pytest.fixture
def captured(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if "-y" in cmd:
            with open(cmd[cmd.index("-y") + 1], "wb") as f:
                f.write(b"x")
        return Ok()

    monkeypatch.setattr(retime_mod.subprocess, "run", fake_run)
    return calls


def test_slow_video_command(captured, tmp_path):
    out = str(tmp_path / "slow.mp4")
    assert slow_video("in.mp4", out, 0.82, "30000/1001", ["-c:v", "libx264"])
    # captured còn chứa cả lệnh ffprobe (tính trần timeout) — lấy lệnh ffmpeg.
    cmd = next(c for c in captured if c[0] == "ffmpeg")
    vf = cmd[cmd.index("-vf") + 1]
    assert "setpts=PTS/0.82" in vf
    assert "fps=30000/1001" in vf
    assert "-fps_mode" in cmd and cmd[cmd.index("-fps_mode") + 1] == "cfr"
    assert "-an" in cmd


def test_slow_background_uses_atempo(captured, tmp_path):
    out = str(tmp_path / "bg.wav")
    assert slow_background("bg_in.wav", out, 0.82)
    cmd = next(c for c in captured if c[0] == "ffmpeg")
    fa = cmd[cmd.index("-filter:a") + 1]
    assert fa.startswith("atempo=0.82")


# ---------------------------- apply_video_speed ---------------------------- #

def test_apply_noop_at_speed_one(tmp_path):
    segs = [seg(1, 0.0, 2.0)]
    s = Settings(video_speed=1.0)
    assert apply_video_speed("in.mp4", None, segs, str(tmp_path), s) is None
    assert segs[0]["start"] == 0.0


def test_apply_rescales_by_measured_ratio(monkeypatch, tmp_path):
    segs = [seg(1, 0.0, 2.0), seg(2, 4.0, 8.0)]
    s = Settings(video_speed=0.8)
    monkeypatch.setattr(retime_mod, "probe_video_info", lambda p: (10.0, "25"))
    monkeypatch.setattr(retime_mod, "slow_video", lambda *a, **k: True)
    # Encoder produced 12.6s where theory says 12.5 — measured ratio wins.
    monkeypatch.setattr(retime_mod, "probe_duration", lambda p: 12.6)
    out = apply_video_speed("in.mp4", None, segs, str(tmp_path), s)
    assert out is not None
    video, bg, scale = out
    assert video.endswith("slowed_video.mp4")
    assert bg is None
    assert abs(scale - 1.26) < 1e-9
    assert abs(segs[1]["start"] - 4.0 * 1.26) < 1e-6
    assert "slot" in segs[0]                        # slots re-annotated
    # Marker persisted for resume reuse (bố cục mới: nằm trong data/).
    with open(os.path.join(str(tmp_path), "data", "slowed_video.json")) as f:
        assert json.load(f)["speed"] == 0.8


def test_apply_failure_returns_none_untouched(monkeypatch, tmp_path):
    segs = [seg(1, 0.0, 2.0)]
    s = Settings(video_speed=0.8)
    monkeypatch.setattr(retime_mod, "probe_video_info", lambda p: (10.0, "25"))
    monkeypatch.setattr(retime_mod, "slow_video", lambda *a, **k: False)
    assert apply_video_speed("in.mp4", None, segs, str(tmp_path), s) is None
    assert segs[0]["start"] == 0.0                  # timeline untouched


def test_apply_reuses_cached_encode(monkeypatch, tmp_path):
    segs = [seg(1, 0.0, 2.0)]
    s = Settings(video_speed=0.8)
    (tmp_path / "data").mkdir()
    out_video = tmp_path / "data" / "slowed_video.mp4"
    out_video.write_bytes(b"x")
    (tmp_path / "data" / "slowed_video.json").write_text('{"speed": 0.8}')
    monkeypatch.setattr(retime_mod, "probe_video_info", lambda p: (10.0, "25"))
    monkeypatch.setattr(retime_mod, "probe_duration", lambda p: 12.5)
    encoded = []
    monkeypatch.setattr(retime_mod, "slow_video",
                        lambda *a, **k: encoded.append(1) or True)
    out = apply_video_speed("in.mp4", None, segs, str(tmp_path), s)
    assert out is not None
    assert not encoded                              # no re-encode
