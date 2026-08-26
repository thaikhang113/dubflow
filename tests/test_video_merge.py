"""Tests for merge_video ffmpeg command construction.

ffmpeg/ffprobe are monkeypatched — no real encoding happens.
"""
import pytest
from pathlib import Path

from autodub.media import video as video_mod

BAND = {"x": 0.0, "y": 0.85, "w": 1.0, "h": 0.12}


@pytest.fixture
def paths(tmp_path):
    """Create the input files merge_video checks for."""
    v = tmp_path / "in.mp4"
    a = tmp_path / "dub.wav"
    s = tmp_path / "vi.srt"
    for p in (v, a, s):
        p.write_bytes(b"x")
    return {
        "video": str(v), "audio": str(a), "srt": str(s),
        "out": str(tmp_path / "out.mp4"),
    }


@pytest.fixture
def captured(monkeypatch):
    """Capture the ffmpeg argv instead of running it (encoder pinned to CPU)."""
    calls = []

    class Ok:
        returncode = 0
        stdout = (
            '{"format":{"duration":"2.0"},'
            '"streams":[{"codec_type":"video"},{"codec_type":"audio"}]}'
        )
        stderr = ""

    def fake_run(cmd, **kw):
        # merge_video giờ gọi thêm ffprobe (tính trần timeout) — chỉ giữ
        # lệnh ffmpeg vì các assert đều nhắm vào nó.
        if cmd[0] == "ffmpeg":
            calls.append(cmd)
            from pathlib import Path
            Path(cmd[-1]).write_bytes(b"ok")
        return Ok()

    monkeypatch.setattr(video_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(video_mod, "probe_dimensions", lambda p: (1920, 1080))
    monkeypatch.setattr(video_mod, "_resolve_encoder", lambda: (
        "CPU (libx264)",
        ("-c:v", "libx264", "-preset", "veryfast", "-crf", "20")))
    return calls


def get_opt(cmd: list[str], flag: str) -> str | None:
    return cmd[cmd.index(flag) + 1] if flag in cmd else None


# --------------------------- default: audio only --------------------------- #

def test_default_stream_copies_video(paths, captured):
    video_mod.merge_video(paths["video"], paths["audio"], paths["out"])
    cmd = captured[0]
    assert get_opt(cmd, "-c:v") == "copy"
    assert "-filter_complex" not in cmd
    assert "-c:s" not in cmd


# --------------------------- soft subs --------------------------- #

def test_soft_subs_mux_without_reencode(paths, captured):
    video_mod.merge_video(
        paths["video"], paths["audio"], paths["out"],
        srt_path=paths["srt"], subtitle_mode="soft")
    cmd = captured[0]
    assert get_opt(cmd, "-c:v") == "copy"       # key benefit of soft subs
    assert get_opt(cmd, "-c:s") == "mov_text"
    assert cmd.count("-i") == 3                 # video + audio + srt
    assert "language=und" in cmd                # default when no lang passed


def test_soft_subs_language_tag(paths, captured):
    video_mod.merge_video(
        paths["video"], paths["audio"], paths["out"],
        srt_path=paths["srt"], subtitle_mode="soft", subtitle_lang="vie")
    assert "language=vie" in captured[0]

def test_logo_and_soft_subs_map_separate_inputs(paths, captured):
    logo = paths["video"].replace("in.mp4", "logo.png")
    from pathlib import Path
    Path(logo).write_bytes(b"png")
    video_mod.merge_video(
        paths["video"], paths["audio"], paths["out"],
        srt_path=paths["srt"], subtitle_mode="soft", logo_path=logo,
    )
    cmd = captured[0]
    assert cmd.count("-i") == 4
    assert "3:0" in cmd


# --------------------------- burn subs --------------------------- #

def test_burn_reencodes_and_maps_vout(paths, captured):
    video_mod.merge_video(
        paths["video"], paths["audio"], paths["out"],
        srt_path=paths["srt"], subtitle_mode="burn")
    cmd = captured[0]
    assert get_opt(cmd, "-c:v") == "libx264"
    assert get_opt(cmd, "-map") == "[vout]"
    assert "subtitles=" in get_opt(cmd, "-filter_complex")
    assert get_opt(cmd, "-pix_fmt") == "yuv420p"
    assert get_opt(cmd, "-ar") == "48000"


# --------------------------- blur --------------------------- #

def test_blur_forces_reencode_even_without_subs(paths, captured):
    video_mod.merge_video(
        paths["video"], paths["audio"], paths["out"], blur_regions=[BAND])
    cmd = captured[0]
    assert get_opt(cmd, "-c:v") == "libx264"
    fc = get_opt(cmd, "-filter_complex")
    assert "boxblur" in fc and "subtitles" not in fc


def test_blur_with_soft_subs_combines_both(paths, captured):
    """Soft subs + blur: filtergraph for blur, plus a real subtitle track."""
    video_mod.merge_video(
        paths["video"], paths["audio"], paths["out"],
        srt_path=paths["srt"], subtitle_mode="soft", blur_regions=[BAND])
    cmd = captured[0]
    assert "boxblur" in get_opt(cmd, "-filter_complex")
    assert get_opt(cmd, "-c:s") == "mov_text"
    assert get_opt(cmd, "-c:v") == "libx264"     # blur still needs re-encode


def test_blur_skipped_when_regions_empty(paths, captured):
    video_mod.merge_video(
        paths["video"], paths["audio"], paths["out"], blur_regions=[])
    assert get_opt(captured[0], "-c:v") == "copy"

def test_logo_overlay_uses_second_video_input_and_fixed_region(paths, captured):
    logo = paths["video"].replace("in.mp4", "logo.png")
    from pathlib import Path
    Path(logo).write_bytes(b"png")
    video_mod.merge_video(
        paths["video"], paths["audio"], paths["out"],
        blur_regions=[BAND], logo_path=logo,
        logo_region={"x": 0.75, "y": 0.05, "w": 0.18, "h": 0.1},
    )
    cmd = captured[0]
    assert cmd.count("-i") == 3
    graph = get_opt(cmd, "-filter_complex")
    assert "[2:v]" in graph
    assert "overlay=" in graph

def test_logo_overlay_uses_default_region_when_position_is_not_set(
    paths, captured
):
    logo = paths["video"].replace("in.mp4", "logo.png")
    from pathlib import Path
    Path(logo).write_bytes(b"png")
    video_mod.merge_video(
        paths["video"], paths["audio"], paths["out"], logo_path=logo,
    )
    graph = get_opt(captured[0], "-filter_complex")
    assert "[2:v]" in graph
    assert "overlay=1459:43" in graph

def test_branding_assets_validate_paths(paths):
    with pytest.raises(FileNotFoundError):
        video_mod.merge_video(
            paths["video"], paths["audio"], paths["out"],
            logo_path=paths["out"] + ".missing",
        )


def test_compose_intro_outro_uses_concat_filter(paths, captured):
    intro = paths["video"].replace("in.mp4", "intro.mp4")
    outro = paths["video"].replace("in.mp4", "outro.mp4")
    from pathlib import Path
    Path(intro).write_bytes(b"intro")
    Path(outro).write_bytes(b"outro")
    video_mod.compose_video(
        paths["video"], paths["out"], intro_path=intro, outro_path=outro)
    cmd = captured[-1]
    assert cmd.count("-i") == 3
    assert "concat=n=3:v=1:a=1" in " ".join(cmd)


def test_reencode_uses_nvenc_when_available(paths, captured, monkeypatch):
    monkeypatch.setattr(video_mod, "_resolve_encoder", lambda: (
        "NVIDIA NVENC",
        ("-c:v", "h264_nvenc", "-preset", "p5", "-cq", "23", "-b:v", "0")))
    video_mod.merge_video(
        paths["video"], paths["audio"], paths["out"],
        srt_path=paths["srt"], subtitle_mode="burn")
    cmd = captured[0]
    assert get_opt(cmd, "-c:v") == "h264_nvenc"
    assert get_opt(cmd, "-pix_fmt") == "yuv420p"


def test_linux_amd_vaapi_encoder_is_selected_after_probe(monkeypatch):
    monkeypatch.setattr(video_mod.sys, "platform", "linux")
    monkeypatch.setattr(video_mod.os.path, "exists",
                        lambda path: path == "/dev/dri/renderD128")
    monkeypatch.setattr(video_mod, "_encoder_works",
                        lambda *args: "h264_vaapi" in args)
    video_mod._resolve_encoder.cache_clear()

    name, args = video_mod._resolve_encoder()

    assert name == "AMD VAAPI"
    assert "h264_vaapi" in args
    assert "format=nv12,hwupload" in args
    video_mod._resolve_encoder.cache_clear()


def test_vaapi_render_uses_nv12_upload_filter(paths, captured, monkeypatch):
    monkeypatch.setattr(video_mod, "_resolve_encoder", lambda: (
        "AMD VAAPI",
        ("-vaapi_device", "/dev/dri/renderD128", "-vf",
         "format=nv12,hwupload", "-c:v", "h264_vaapi", "-qp", "23"),
    ))
    video_mod.merge_video(
        paths["video"], paths["audio"], paths["out"],
        srt_path=paths["srt"], subtitle_mode="burn")
    cmd = captured[0]
    assert get_opt(cmd, "-c:v") == "h264_vaapi"
    assert get_opt(cmd, "-vf") == "format=nv12,hwupload"
    assert get_opt(cmd, "-pix_fmt") == "nv12"


def test_vaapi_failure_cpu_retry_removes_vaapi_options(paths, monkeypatch):
    calls = []

    class Bad:
        returncode = 1
        stdout = ""
        stderr = "vaapi failed"

    class Good:
        returncode = 0
        stdout = (
            '{"format":{"duration":"2.0"},'
            '"streams":[{"codec_type":"video"},{"codec_type":"audio"}]}'
        )
        stderr = ""

    def fake_run(cmd, **kw):
        if cmd[0] == "ffmpeg":
            calls.append(cmd)
            Path(cmd[-1]).write_bytes(b"ok")
            return Bad() if len(calls) == 1 else Good()
        return Good()

    monkeypatch.setattr(video_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(video_mod, "probe_dimensions", lambda p: (1920, 1080))
    monkeypatch.setattr(video_mod, "_resolve_encoder", lambda: (
        "AMD VAAPI",
        ("-vaapi_device", "/dev/dri/renderD128", "-vf",
         "format=nv12,hwupload", "-c:v", "h264_vaapi", "-qp", "23"),
    ))

    video_mod.merge_video(
        paths["video"], paths["audio"], paths["out"],
        srt_path=paths["srt"], subtitle_mode="burn")

    assert len(calls) == 2
    assert "-vaapi_device" not in calls[1]
    assert "-vf" not in calls[1]
    assert get_opt(calls[1], "-c:v") == "libx264"
    assert get_opt(calls[1], "-pix_fmt") == "yuv420p"

def test_mirror_adds_hflip_and_keeps_subtitles_after_flip(paths, captured):
    video_mod.merge_video(
        paths["video"], paths["audio"], paths["out"],
        srt_path=paths["srt"], subtitle_mode="burn", mirror=True)
    graph = get_opt(captured[0], "-filter_complex")
    assert graph.startswith("[0:v]hflip[vflip];[vflip]")
    assert graph.index("hflip") < graph.index("subtitles")

def test_hardware_failure_retries_with_cpu(paths, monkeypatch):
    calls = []

    class Bad:
        returncode = 1
        stdout = ""
        stderr = "hardware encoder failed"

    class Good:
        returncode = 0
        stdout = (
            '{"format":{"duration":"2.0"},'
            '"streams":[{"codec_type":"video"},{"codec_type":"audio"}]}'
        )
        stderr = ""

    def fake_run(cmd, **kw):
        if cmd[0] == "ffmpeg":
            calls.append(cmd)
            from pathlib import Path
            Path(cmd[-1]).write_bytes(b"ok")
            return Bad() if len(calls) == 1 else Good()
        return Good()

    monkeypatch.setattr(video_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(video_mod, "probe_dimensions", lambda p: (1920, 1080))
    monkeypatch.setattr(video_mod, "_resolve_encoder", lambda: (
        "AMD AMF",
        ("-c:v", "h264_amf", "-quality", "speed", "-rc", "cqp",
         "-qp_i", "23", "-qp_p", "23")))

    video_mod.merge_video(
        paths["video"], paths["audio"], paths["out"],
        srt_path=paths["srt"], subtitle_mode="burn")

    assert len(calls) == 2
    assert get_opt(calls[0], "-c:v") == "h264_amf"
    assert get_opt(calls[1], "-c:v") == "libx264"


# --------------------------- validation --------------------------- #

def test_rejects_unknown_mode(paths, captured):
    with pytest.raises(ValueError, match="Invalid subtitle_mode"):
        video_mod.merge_video(
            paths["video"], paths["audio"], paths["out"], subtitle_mode="hard")


def test_rejects_mode_without_srt(paths, captured):
    with pytest.raises(ValueError, match="requires srt_path"):
        video_mod.merge_video(
            paths["video"], paths["audio"], paths["out"], subtitle_mode="burn")


def test_rejects_missing_srt_file(paths, captured):
    with pytest.raises(FileNotFoundError, match="Subtitle file"):
        video_mod.merge_video(
            paths["video"], paths["audio"], paths["out"],
            srt_path=paths["srt"] + ".nope", subtitle_mode="burn")


def test_ffmpeg_failure_raises(paths, monkeypatch):
    class Bad:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(video_mod.subprocess, "run", lambda cmd, **kw: Bad())
    with pytest.raises(RuntimeError, match="boom"):
        video_mod.merge_video(paths["video"], paths["audio"], paths["out"])


# --------------------------- probe --------------------------- #

def test_probe_dimensions_parses_json(monkeypatch):
    class Ok:
        returncode = 0
        stdout = '{"streams":[{"width":1280,"height":720}]}'
        stderr = ""

    monkeypatch.setattr(video_mod.subprocess, "run", lambda cmd, **kw: Ok())
    assert video_mod.probe_dimensions("x.mp4") == (1280, 720)


def test_probe_dimensions_raises_on_bad_output(monkeypatch):
    class Ok:
        returncode = 0
        stdout = "{}"
        stderr = ""

    monkeypatch.setattr(video_mod.subprocess, "run", lambda cmd, **kw: Ok())
    with pytest.raises(RuntimeError, match="Could not read dimensions"):
        video_mod.probe_dimensions("x.mp4")
