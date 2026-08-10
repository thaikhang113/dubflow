import json
import os
import subprocess
from functools import lru_cache

from autodub.utils import ffmpeg_timeout_s, setup_logging

logger = setup_logging("autodub.video_merger")


def probe_duration_s(video_path: str) -> float | None:
    """Thời lượng (giây) của media qua ffprobe; None nếu không đọc được.

    Dùng để tính trần timeout cho các lệnh encode dài — không phải giá trị
    chính xác tuyệt đối nên lỗi thì cứ trả None, caller tự dùng trần rộng.
    """
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, timeout=60,
        )
        return float(result.stdout.strip()) if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


@lru_cache(maxsize=None)
def _encoder_works(*args: str) -> bool:
    """True nếu ffmpeg mã hóa được thật bằng bộ mã hóa này.

    Chỉ liệt kê trong ``-encoders`` là không đủ: driver cũ hoặc máy không có
    card tương ứng vẫn liệt kê mà chạy là lỗi. Encode thử một khung vào
    null-sink là cách duy nhất chắc chắn.
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi",
             "-i", "color=black:s=256x256:d=0.1", *args, "-f", "null", "-"],
            capture_output=True, text=True, timeout=30,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


#: Các bộ mã hóa phần cứng theo thứ tự ưu tiên, kèm tham số chất lượng
#: tương đương crf 23 của libx264. NVIDIA → Intel (QSV) → AMD (AMF).
#: Máy không có GPU nào trong số này rơi về libx264 trên CPU.
_HW_ENCODERS: tuple[tuple[str, list[str]], ...] = (
    ("NVIDIA NVENC",
     ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "23", "-b:v", "0"]),
    ("Intel QuickSync",
     ["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", "23"]),
    ("AMD AMF",
     ["-c:v", "h264_amf", "-quality", "speed", "-rc", "cqp", "-qp_i", "23",
      "-qp_p", "23"]),
)


@lru_cache(maxsize=1)
def _resolve_encoder() -> tuple[str, tuple[str, ...]]:
    """Bộ mã hóa nhanh nhất máy này chạy được: (tên dễ đọc, argv)."""
    for name, args in _HW_ENCODERS:
        if _encoder_works(*args):
            return name, tuple(args)
    return ("CPU (libx264)",
            ("-c:v", "libx264", "-preset", "veryfast", "-crf", "20"))


def video_codec_args() -> list[str]:
    """Encoder argv shared by every re-encode in the app (merge, retime).

    Ưu tiên mã hóa bằng GPU (NVENC/QSV/AMF) — nhanh gấp nhiều lần libx264 ở
    chất lượng tương đương với video lồng tiếng; máy không có thì dùng CPU.
    veryfast ≈ 2-3× faster than medium at the same crf; the size bump is
    irrelevant for upload-and-delete dub outputs.
    """
    return list(_resolve_encoder()[1])


def video_encoder_name() -> str:
    """Tên bộ mã hóa đang dùng — để ghi vào nhật ký cho người dùng thấy."""
    return _resolve_encoder()[0]


def probe_dimensions(video_path: str) -> tuple[int, int]:
    """Return DISPLAY (width, height) of the first video stream via ffprobe.

    Phone videos often store 1920x1080 with a 90° rotation tag; ffmpeg's
    decoder auto-rotates before the filtergraph, so blur/subtitle coordinates
    must be scaled against the rotated (display) dimensions — otherwise blurs
    land in the wrong place and crops can exceed the frame.
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,side_data_list",
        "-of", "json",
        video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {video_path}: {result.stderr}")
    try:
        stream = json.loads(result.stdout)["streams"][0]
        w, h = int(stream["width"]), int(stream["height"])
    except (KeyError, IndexError, ValueError, json.JSONDecodeError) as e:
        raise RuntimeError(f"Could not read dimensions from {video_path}: {e}") from e
    rotation = 0
    for sd in stream.get("side_data_list") or []:
        if "rotation" in sd:
            try:
                rotation = int(sd["rotation"])
            except (TypeError, ValueError):
                rotation = 0
            break
    if rotation % 180 != 0:
        w, h = h, w
    return w, h


def render_preview_clip(
    video_path: str,
    audio_path: str,
    output_path: str,
    start_s: float,
    end_s: float,
    srt_path: str | None = None,
    subtitle_style: dict | None = None,
    speed: float | None = None,
    fps: str | None = None,
    height: int = 480,
) -> str:
    """Cắt một đoạn ngắn của video và ghép bản âm thanh xem thử vào.

    Đường đi NHANH cho việc nghe thử một câu trước khi xuất cả phim: chỉ
    mã hóa vài giây quanh câu đang chọn, hạ xuống ``height`` điểm ảnh và
    dùng ``-preset ultrafast`` — vài giây là xong thay vì vài phút.

    ``start_s``/``end_s`` tính trên timeline của TỆP NGUỒN. ``srt_path``
    (nếu có) phải mang mốc thời gian ĐÃ DỜI về 0 tại ``start_s``, vì với
    ``-ss`` đặt trước ``-i`` thì timestamp đầu ra bắt đầu từ 0. ``speed``
    < 1.0 làm chậm ngay trong lượt mã hóa (dự án dùng đường làm chậm gộp).
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio not found: {audio_path}")

    filters = []
    if speed is not None and speed < 0.999:
        filters.append(f"setpts=PTS/{speed}")
        if fps:
            filters.append(f"fps={fps}")
    # Không phóng to video vốn đã nhỏ hơn 480 điểm; -2 giữ chiều rộng chẵn.
    filters.append(f"scale=-2:'min({height},ih)'")
    if srt_path and os.path.exists(srt_path):
        from autodub.media.subtitle import (build_force_style,
                                            escape_subtitles_path)
        from autodub.utils import bundled_font_files, fonts_dir
        subs = f"subtitles='{escape_subtitles_path(srt_path)}'"
        if bundled_font_files():
            subs += f":fontsdir='{escape_subtitles_path(fonts_dir())}'"
        if not srt_path.lower().endswith(".ass"):
            subs += f":force_style='{build_force_style(subtitle_style)}'"
        filters.append(subs)

    cmd = [
        "ffmpeg", "-ss", f"{start_s:.3f}", "-to", f"{end_s:.3f}",
        "-i", video_path, "-i", audio_path,
        "-filter:v", ",".join(filters),
        "-map", "0:v:0", "-map", "1:a",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest", "-y", output_path,
    ]
    logger.info(f"Rendering preview clip {start_s:.1f}s–{end_s:.1f}s → "
                f"{output_path}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=ffmpeg_timeout_s(end_s - start_s))
    except subprocess.TimeoutExpired:
        raise RuntimeError("FFmpeg treo khi dựng đoạn xem thử")
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg preview failed: {result.stderr[:400]}")
    return output_path


def merge_video(
    video_path: str,
    audio_path: str,
    output_path: str,
    srt_path: str | None = None,
    subtitle_mode: str = "none",
    blur_regions: list[dict] | None = None,
    subtitle_style: dict | None = None,
    subtitle_lang: str = "und",
    speed: float | None = None,
    fps: str | None = None,
) -> str:
    """Mux the dubbed audio into the video, optionally adding subtitles/blur.

    ``subtitle_mode``:

    - ``none`` — audio only (default; stream-copies video, fastest)
    - ``soft`` — embed the SRT as a toggleable subtitle track (still no re-encode)
    - ``burn`` — draw subtitles into the pixels (requires a video re-encode)

    ``blur_regions`` blurs rectangles of the frame to cover hardcoded source
    captions. Coordinates are normalized 0..1 dicts (``x``/``y``/``w``/``h``,
    optional ``t_start``/``t_end``). Any blur forces a re-encode, so it is
    applied in the same pass as burned-in subtitles.

    ``speed`` (< 1.0) slows the video INSIDE the same encode pass
    (``setpts=PTS/speed,fps=<fps>`` prepended to the filtergraph) — the
    fused path for ``VIDEO_SPEED`` when a re-encode happens anyway. Callers
    must pass blur/subtitle timestamps already rescaled to the slowed
    timeline. Requires ``fps`` (ffprobe rational); forces a re-encode even
    without subs/blur.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio not found: {audio_path}")

    if subtitle_mode not in ("none", "soft", "burn"):
        raise ValueError(f"Invalid subtitle_mode: {subtitle_mode!r}")
    if subtitle_mode != "none" and not srt_path:
        raise ValueError(f"subtitle_mode={subtitle_mode!r} requires srt_path")
    if srt_path and subtitle_mode != "none" and not os.path.exists(srt_path):
        raise FileNotFoundError(f"Subtitle file not found: {srt_path}")

    from autodub.media.subtitle import build_filter_complex

    burn_srt = srt_path if subtitle_mode == "burn" else None
    filter_complex = None
    if blur_regions or burn_srt:
        width, height = probe_dimensions(video_path)
        filter_complex = build_filter_complex(
            blur_regions, width, height, burn_srt, subtitle_style
        )

    apply_speed = speed is not None and speed < 0.999
    if apply_speed:
        if not fps:
            raise ValueError("speed requires fps (ffprobe rational)")
        setpts = f"setpts=PTS/{speed},fps={fps}"
        if filter_complex:
            # setpts BEFORE blur/subs: their timestamps are on the slowed
            # timeline, so the frames must already be retimed when they apply.
            filter_complex = (f"[0:v]{setpts}[vslow];"
                              + filter_complex.replace("[0:v]", "[vslow]", 1))
        else:
            filter_complex = f"[0:v]{setpts}[vout]"

    cmd = ["ffmpeg", "-i", video_path, "-i", audio_path]
    if subtitle_mode == "soft":
        cmd += ["-i", srt_path]

    if filter_complex:
        # Re-encode: the filtergraph rewrites pixels, so -c:v copy is impossible.
        codec = video_codec_args()
        cmd += [
            "-filter_complex", filter_complex,
            "-map", "[vout]", "-map", "1:a",
            *codec,
            "-pix_fmt", "yuv420p",
        ]
        if apply_speed:
            cmd += ["-fps_mode", "cfr"]
    else:
        # 0:v:0 (not 0:v): downloaded MP4s can carry an attached-picture
        # thumbnail stream that would also be stream-copied.
        cmd += ["-c:v", "copy", "-map", "0:v:0", "-map", "1:a"]

    if subtitle_mode == "soft":
        # mov_text is the subtitle codec MP4 containers accept.
        cmd += ["-map", "2:0", "-c:s", "mov_text",
                "-metadata:s:s:0", f"language={subtitle_lang}"]

    cmd += ["-c:a", "aac", "-b:a", "192k", "-y", output_path]

    what = ["audio"]
    if subtitle_mode != "none":
        what.append(f"{subtitle_mode} subs")
    if blur_regions:
        what.append(f"{len(blur_regions)} blur region(s)")
    if apply_speed:
        what.append(f"speed {speed}x")
    logger.info(f"Merging video + {' + '.join(what)} → {output_path}")
    if filter_complex:
        logger.info("Re-encoding video (filters applied) — this takes a while")

    # Trần timeout theo thời lượng thật: stream-copy thì 4x là quá rộng;
    # re-encode CPU trên máy yếu có thể chậm hơn realtime nên nhân 8.
    dur = probe_duration_s(video_path)
    timeout = (max(900, int(dur * 8)) if filter_complex and dur
               else ffmpeg_timeout_s(dur))
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"FFmpeg treo quá {timeout}s khi ghép video — kiểm tra file "
            f"nguồn có bị khóa hoặc driver GPU có ổn định không")
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg merge failed: {result.stderr}")

    logger.info(f"Video merged: {output_path}")
    return output_path
