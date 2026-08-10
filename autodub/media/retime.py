"""Uniform video slow-down: give the dub room by slowing the WHOLE video.

One knob — ``VIDEO_SPEED`` (e.g. 0.82) — slows every frame and the background
track by the same factor, so a Vietnamese dub that runs ~20% longer than the
Chinese original simply fits. No piecewise stretching, no per-segment fitting,
no trimming: the voice reads at its natural pace on a uniformly longer
timeline, and if lines still collide the user lowers ``VIDEO_SPEED`` and
re-runs (TTS clips are cached, so a re-run is cheap).

Segment timestamps are rescaled by the MEASURED length ratio of the slowed
file (not the theoretical 1/speed) so audio placement, subtitles and blur
regions stay frame-locked to the picture.

:func:`apply_video_speed` returns ``None`` on any ffmpeg failure — the
pipeline then proceeds with the original video and timeline unchanged.
"""
from __future__ import annotations

import json
import os
import subprocess

from autodub.utils import ffmpeg_timeout_s, setup_logging

logger = setup_logging("autodub.retime")


# --------------------------------------------------------------- probes ---- #

def probe_video_info(video_path: str) -> tuple[float, str]:
    """(duration_seconds, fps_string) of the first video stream.

    ``fps_string`` keeps ffprobe's exact rational (e.g. "30000/1001") so the
    slowed encode reproduces the source rate without float rounding.
    """
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=avg_frame_rate:format=duration",
         "-of", "json", video_path],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {video_path}: {result.stderr[:200]}")
    data = json.loads(result.stdout)
    duration = float(data["format"]["duration"])
    fps = str(data["streams"][0]["avg_frame_rate"])
    if not fps or fps == "0/0":
        fps = "25"
    return duration, fps


def probe_duration(path: str) -> float | None:
    """Container duration in seconds, or None if it cannot be read."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", path],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        return None
    try:
        return float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return None


# --------------------------------------------------------------- ffmpeg ---- #

def slow_video(video_path: str, output_path: str, speed: float,
               fps: str, codec_args: list[str]) -> bool:
    """Re-encode the whole video at ``speed`` (< 1.0 = slower, longer).

    ``fps=<r>`` + ``-fps_mode cfr`` pin constant frame rate so players and
    the mux behave; audio is dropped (the dub track is muxed separately).
    """
    cmd = [
        "ffmpeg", "-v", "error", "-i", video_path, "-an",
        "-vf", f"setpts=PTS/{speed},fps={fps}",
        "-fps_mode", "cfr",
        *codec_args,
        "-pix_fmt", "yuv420p",
        "-y", output_path,
    ]
    # Encode lại toàn bộ video — trần theo thời lượng nguồn, CPU yếu vẫn dư.
    dur = probe_duration(video_path)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=max(900, int(dur * 8)) if dur
                                else ffmpeg_timeout_s(None))
        err = result.stderr[:200]
        failed = result.returncode != 0
    except subprocess.TimeoutExpired:
        failed, err = True, "ffmpeg treo (quá trần thời gian)"
    if (failed or not os.path.exists(output_path)
            or os.path.getsize(output_path) == 0):
        logger.error(f"Slow video {speed}x failed: {err}")
        return False
    return True


def slow_background(background_path: str, output_path: str,
                    speed: float) -> bool:
    """Slow the background track by the same factor (atempo accepts ≥0.5)."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", background_path,
             "-filter:a", f"atempo={max(0.5, min(2.0, speed)):.6f}",
             "-acodec", "pcm_s16le", "-y", output_path],
            capture_output=True, text=True,
            timeout=ffmpeg_timeout_s(probe_duration(background_path)),
        )
        err = result.stderr[:200]
        failed = result.returncode != 0
    except subprocess.TimeoutExpired:
        failed, err = True, "ffmpeg treo (quá trần thời gian)"
    if (failed or not os.path.exists(output_path)
            or os.path.getsize(output_path) == 0):
        logger.error(f"Slow background {speed}x failed: {err}")
        return False
    return True


# ------------------------------------------------------------- rescale ----- #

def rescale_segments(segments: list[dict], scale: float) -> None:
    """Stretch every timestamp by ``scale`` (>1 = longer timeline), in place.

    Callers must re-run :func:`autodub.text.translate_hint.annotate_slots`
    afterwards so slots reflect the stretched gaps.
    """
    for seg in segments:
        seg["start"] = round(float(seg["start"]) * scale, 3)
        seg["end"] = round(float(seg["end"]) * scale, 3)
        seg["duration"] = round(seg["end"] - seg["start"], 3)


def rescale_blur_regions(blur_regions: list[dict], scale: float) -> list[dict]:
    """Blur windows follow the slowed timeline (regions without times pass through)."""
    out = []
    for r in blur_regions:
        r = dict(r)
        for key in ("t_start", "t_end"):
            if r.get(key) is not None:
                r[key] = round(float(r[key]) * scale, 3)
        out.append(r)
    return out


# ---------------------------------------------------------- orchestrator --- #

def apply_video_speed(
    video_path: str,
    background_path: str | None,
    segments: list[dict],
    work_dir: str,
    settings,
) -> tuple[str, str | None, float] | None:
    """Slow the whole video to ``settings.video_speed`` and rescale the timeline.

    Mutates ``segments`` onto the slowed timeline and returns
    ``(slowed_video, slowed_background_or_None, scale)``. Returns ``None``
    when speed is 1.0 or on any ffmpeg failure (caller proceeds unchanged).
    The expensive encode is cached: a resume run with the same speed reuses
    ``slowed_video.mp4`` via the marker file.
    """
    from autodub.media.video import video_codec_args
    from autodub.text.translate_hint import annotate_slots
    from autodub.workdir import data_path

    speed = float(settings.video_speed)
    if speed >= 0.999:
        return None

    try:
        orig_duration, fps = probe_video_info(video_path)
        out_video = data_path(work_dir, "slowed_video.mp4", create_dir=True)
        marker = data_path(work_dir, "slowed_video.json")

        cached = False
        if os.path.isfile(out_video) and os.path.isfile(marker):
            try:
                with open(marker, encoding="utf-8") as f:
                    cached = abs(json.load(f).get("speed", 0) - speed) < 1e-6
            except (OSError, ValueError):
                cached = False

        if cached:
            logger.info(f"Dùng lại video đã làm chậm ({speed}x) từ lần chạy "
                        "trước — đỡ chờ")
        else:
            logger.info(
                f"Đang làm chậm video xuống {speed}x để giọng đọc tiếng Việt "
                f"có đủ chỗ (video {orig_duration:.0f} giây sẽ dài thành "
                f"~{orig_duration / speed:.0f} giây) — mất vài phút, "
                "chờ chút nhé..."
            )
            if not slow_video(video_path, out_video, speed, fps,
                              video_codec_args()):
                logger.warning("Làm chậm video thất bại — dùng video gốc")
                return None
            with open(marker, "w", encoding="utf-8") as f:
                json.dump({"speed": speed}, f)

        # Đường rời đang chạy — marker của đường gộp (nếu lần trước dùng)
        # thành cũ, để lại sẽ làm trình chỉnh sửa co giãn timeline hai lần.
        stale = data_path(work_dir, "deferred_speed.json")
        if os.path.isfile(stale):
            os.remove(stale)

        new_duration = probe_duration(out_video)
        # Measured ratio beats theoretical 1/speed: frame rounding shifts the
        # tail by a few ms and subs/audio must match the real file.
        scale = (new_duration / orig_duration
                 if new_duration and orig_duration else 1.0 / speed)

        out_bg: str | None = None
        if background_path and os.path.exists(background_path):
            out_bg = data_path(work_dir, "slowed_background.wav")
            if not slow_background(background_path, out_bg, speed):
                logger.warning("Làm chậm nhạc nền thất bại — dùng video gốc")
                return None

        rescale_segments(segments, scale)
        annotate_slots(segments)
        logger.info(f"Video đã chậm xong ({new_duration or 0:.0f} giây) — "
                    "giọng đọc vẫn giữ tốc độ tự nhiên")
        return out_video, out_bg, scale
    except Exception as e:
        logger.warning(f"Làm chậm video lỗi ({e}) — dùng video gốc")
        return None


def defer_video_speed(
    video_path: str,
    background_path: str | None,
    segments: list[dict],
    work_dir: str,
    settings,
) -> tuple[str | None, float, str] | None:
    """Chuẩn bị làm chậm video NHƯNG dời phần mã hóa sang bước ghép cuối.

    Khi video đằng nào cũng phải mã hóa lại (ghi phụ đề / che chữ),
    ``setpts`` có thể gộp vào chính lượt mã hóa đó — tiết kiệm nguyên một
    lần encode toàn bộ video so với :func:`apply_video_speed`. Ở đây chỉ:
    làm chậm nhạc nền (atempo, nhanh), co giãn timeline theo tỷ lệ lý thuyết
    ``1/speed`` (đúng tỷ lệ ``setpts`` sẽ dùng), và ghi marker
    ``deferred_speed.json`` để trình chỉnh sửa xuất lại đúng nhịp.

    Trả về ``(slowed_background_or_None, scale, fps)`` — caller truyền
    ``speed``/``fps`` vào ``merge_video``. ``None`` khi speed là 1.0 hoặc
    lỗi (caller rơi về :func:`apply_video_speed`).
    """
    from autodub.text.translate_hint import annotate_slots
    from autodub.workdir import data_path

    speed = float(settings.video_speed)
    if speed >= 0.999:
        return None

    try:
        orig_duration, fps = probe_video_info(video_path)
        scale = 1.0 / speed

        out_bg: str | None = None
        if background_path and os.path.exists(background_path):
            out_bg = data_path(work_dir, "slowed_background.wav",
                               create_dir=True)
            if not slow_background(background_path, out_bg, speed):
                logger.warning("Làm chậm nhạc nền thất bại — quay về đường "
                               "làm chậm rời")
                return None

        # Marker cho trình chỉnh sửa: video gốc + speed/fps để lần xuất lại
        # cũng gộp setpts vào lượt mã hóa của nó. Xóa marker của đường rời
        # (nếu lần chạy trước dùng nó) để hai marker không cãi nhau.
        with open(data_path(work_dir, "deferred_speed.json", create_dir=True),
                  "w", encoding="utf-8") as f:
            json.dump({"speed": speed, "fps": fps}, f)
        stale = data_path(work_dir, "slowed_video.json")
        if os.path.isfile(stale):
            os.remove(stale)

        rescale_segments(segments, scale)
        annotate_slots(segments)
        logger.info(
            f"Làm chậm video ({speed}x) sẽ gộp vào lượt xuất video cuối — "
            f"đỡ nguyên một lần mã hóa (video {orig_duration:.0f} giây thành "
            f"~{orig_duration * scale:.0f} giây)")
        return out_bg, scale, fps
    except Exception as e:
        logger.warning(f"Không gộp được làm chậm vào lượt xuất ({e}) — "
                       "dùng đường làm chậm rời")
        return None
