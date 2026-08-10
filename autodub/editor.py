"""Post-run editing of a finished (or in-progress) dub work directory.

Powers the GUI Segment Editor: load the translated segments, edit a line, re-TTS
just that segment, and rebuild the final audio/video — all reusing the pipeline's
cached artifacts so nothing is recomputed unnecessarily.

The work dir stays the single source of truth: edits are written straight back
to the translated transcript JSON, so a later ``--resume`` sees them too.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from autodub.config import Settings
from autodub.languages import TargetLang, get_target
from autodub.progress import ProgressReporter
from autodub.utils import save_json_atomic, setup_logging, seg_wav_path
from autodub.workdir import data_dir, data_path

logger = setup_logging("autodub.editor")


class EditorError(Exception):
    """Raised when a work dir cannot be edited (missing transcript, etc.)."""


@dataclass
class EditorState:
    work_dir: str
    target: TargetLang
    segments: list[dict]
    video_path: str | None = None
    render_opts: dict = field(default_factory=dict)


RENDER_OPTS_NAME = "render_opts.json"
_VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".mov", ".avi")


def _transcript_path(work_dir: str, target: TargetLang) -> str:
    return data_path(work_dir, target.transcript_name)


def _find_source_video(work_dir: str) -> str | None:
    """The original (non-dubbed) video in the work dir, if present.

    Falls back to the external source recorded in ``source_video.json``
    (runs started from a local file outside work_dir).
    """
    if not os.path.isdir(work_dir):
        return None
    for f in sorted(os.listdir(work_dir)):
        lower = f.lower()
        # slowed_video.mp4 is a derivative of the source — never pick
        # derivatives as the rebuild source.
        if (lower.endswith(_VIDEO_EXTS)
                and not lower.startswith(("dubbed_video", "retimed_video",
                                          "slowed_video"))):
            return os.path.join(work_dir, f)
    from autodub.pipeline import source_video_path
    return source_video_path(work_dir)


def load_render_opts(work_dir: str) -> dict:
    """Read persisted subtitle/blur choices, or an empty dict."""
    path = data_path(work_dir, RENDER_OPTS_NAME)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Could not read {RENDER_OPTS_NAME}: {e}")
    return {}


def save_render_opts(work_dir: str, opts: dict) -> None:
    save_json_atomic(opts, data_path(work_dir, RENDER_OPTS_NAME, create_dir=True))


def load_work_dir(work_dir: str, target_key: str = "vi") -> EditorState:
    """Load the translated segments and context for editing."""
    if not os.path.isdir(work_dir):
        raise EditorError(f"Work directory not found: {work_dir}")
    from autodub import securestore
    if securestore.is_locked(work_dir):
        # Dự án wizard chưa bấm Xuất video — dữ liệu trả phí còn mã hóa.
        raise EditorError(
            "Dự án chưa xuất video nên chưa mở được trong Trình chỉnh sửa. "
            "Mở dự án ở tab Dự án mới và bấm Xuất video trước đã."
        )
    target = get_target(target_key)
    path = _transcript_path(work_dir, target)
    if not os.path.exists(path):
        raise EditorError(
            f"No translation found ({target.transcript_name}). Run the dub first."
        )
    with open(path, encoding="utf-8") as f:
        segments = json.load(f)
    if not isinstance(segments, list) or not segments:
        raise EditorError(f"{target.transcript_name} is not a non-empty segment array")

    return EditorState(
        work_dir=work_dir,
        target=target,
        segments=segments,
        video_path=_find_source_video(work_dir),
        render_opts=load_render_opts(work_dir),
    )


def update_segment_text(
    work_dir: str, seg_id: int, new_text: str, target_key: str = "vi"
) -> None:
    """Ghi một câu vừa sửa trở lại tệp lời thoại."""
    save_segment_texts(work_dir, {seg_id: new_text}, target_key)


def save_segment_texts(
    work_dir: str, edits: dict[int, str], target_key: str = "vi"
) -> list[int]:
    """Ghi nhiều câu vừa sửa trong một lượt.

    Trả về số thứ tự của những câu THẬT SỰ đổi chữ, để lớp gọi biết câu nào
    cần đọc lại giọng. Câu để trống bị chặn trước khi ghi bất cứ thứ gì, nên
    một dòng trống không làm hỏng cả tệp lời thoại.
    """
    return _save_field(work_dir, edits, target_key, field=None,
                       allow_empty=False)


def save_subtitle_texts(
    work_dir: str, edits: dict[int, str], target_key: str = "vi"
) -> list[int]:
    """Ghi phụ đề viết riêng cho từng câu (không đụng tới lời đọc).

    Đây là thứ làm cho việc "sửa phụ đề trực tiếp" thành thật: chữ phụ đề
    được lưu vào trường riêng ``sub_vi``, nên sửa một lỗi chính tả trên phụ
    đề chỉ cần ghi lại phụ đề vào video, không phải đọc lại giọng và càng
    không phải chạy lại cả pipeline.

    Phụ đề trùng y hệt lời đọc thì trường riêng được XÓA đi, để tệp lời thoại
    không phình ra vì dữ liệu thừa.
    """
    from autodub.text.srt import SUBTITLE_FIELD

    return _save_field(work_dir, edits, target_key, field=SUBTITLE_FIELD,
                       allow_empty=True)


def _save_field(work_dir: str, edits: dict[int, str], target_key: str,
                field: str | None, allow_empty: bool) -> list[int]:
    """Phần chung của hai hàm ghi ở trên."""
    target = get_target(target_key)
    path = _transcript_path(work_dir, target)
    if not os.path.exists(path):
        raise EditorError(f"Chưa có bản dịch trong dự án này "
                          f"({target.transcript_name})")

    clean: dict[int, str] = {}
    for seg_id, text in edits.items():
        text = (text or "").strip()
        if not text and not allow_empty:
            raise EditorError(f"Câu {seg_id}: bản dịch không được để trống")
        clean[int(seg_id)] = text

    with open(path, encoding="utf-8") as f:
        segments = json.load(f)

    by_id = {s.get("id"): s for s in segments}
    missing = [i for i in clean if i not in by_id]
    if missing:
        raise EditorError(f"Không tìm thấy câu số: {missing}")

    key = field or target.text_field
    changed: list[int] = []
    for seg_id, text in clean.items():
        seg = by_id[seg_id]
        # Phụ đề trùng lời đọc thì không cần lưu riêng.
        drop = field is not None and (not text
                                      or text == str(seg.get(target.text_field, "")))
        if drop:
            if key in seg:
                seg.pop(key)
                changed.append(seg_id)
            continue
        if seg.get(key) != text:
            seg[key] = text
            changed.append(seg_id)

    if changed:
        # Ghi nguyên khối: tệp lời thoại là nguồn dữ liệu gốc — sập máy giữa
        # lúc ghi không được phép làm hỏng nó (dịch lại tốn thời gian và tiền).
        save_json_atomic(segments, path)
    logger.info(f"Đã lưu {len(changed)} câu vào {target.transcript_name}")
    return sorted(changed)


def set_segment_voice(work_dir: str, seg_id: int, voice: str,
                      target_key: str = "vi") -> bool:
    """Gán (hoặc bỏ) giọng đọc riêng cho MỘT câu.

    ``voice`` rỗng nghĩa là câu quay về giọng chung của dự án — khóa
    ``"voice"`` bị xóa hẳn để tệp lời thoại không phình vì dữ liệu thừa.
    Trả về True nếu có thay đổi thật (GUI dựa vào đó để đánh dấu câu cần
    đọc lại giọng).
    """
    target = get_target(target_key)
    path = _transcript_path(work_dir, target)
    if not os.path.exists(path):
        raise EditorError(f"Chưa có bản dịch trong dự án này "
                          f"({target.transcript_name})")
    with open(path, encoding="utf-8") as f:
        segments = json.load(f)
    seg = next((s for s in segments if s.get("id") == int(seg_id)), None)
    if seg is None:
        raise EditorError(f"Không tìm thấy câu số: {seg_id}")

    voice = (voice or "").strip()
    if voice:
        if str(seg.get("voice", "")) == voice:
            return False
        seg["voice"] = voice
    else:
        if "voice" not in seg:
            return False
        seg.pop("voice")
    save_json_atomic(segments, path)
    logger.info(f"Câu {seg_id}: giọng riêng = {voice or '(giọng chung)'}")
    return True


def _stale_derived_paths(work_dir: str, target: TargetLang, seg_id: int) -> list[str]:
    """Files that no longer match a re-synthesized segment and must be removed.

    Deleting them forces the next rebuild to regenerate from the fresh segment
    wav instead of serving cached (now-wrong) audio/video.
    """
    # Both name widths: 5-digit (current) and 3-digit (legacy work dirs).
    names = [f"seg_{seg_id:05d}.wav", f"seg_{seg_id:03d}.wav"]
    paths = [data_path(work_dir, target.audio_name),
             os.path.join(work_dir, "dubbed_video.mp4")]
    # Voice-speed caches (segments_speedN_NN) and legacy fit/slow dirs.
    dd = data_dir(work_dir)
    if os.path.isdir(dd):
        for d in os.listdir(dd):
            if d.startswith(("segments_speed", "segments_slow", "segments_fit",
                             "segments_post", "segments_timed")):
                paths += [os.path.join(dd, d, n) for n in names]
    return paths


def _remove_with_retry(path: str, attempts: int = 5, delay: float = 0.3) -> None:
    """Remove a file, retrying briefly if another process still holds it.

    On Windows a media player (or an antivirus scan) can keep a wav locked for
    a moment after playback stops; a short retry loop absorbs that instead of
    failing the whole re-synthesis with WinError 32.
    """
    import time

    for attempt in range(attempts):
        try:
            os.remove(path)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def resynth_segment(
    work_dir: str, seg_id: int, settings: Settings,
    target_key: str = "vi", voice: str | None = None,
    synth=None,
) -> dict:
    """Re-run TTS for one segment (strict 1:1 — one line, one clip).

    The clip's wav is keyed by the segment's own id and rendered into the
    real time window until the next line starts (its ``slot``).

    ``synth`` reuses an already-loaded synthesizer — creating one per segment
    would reload the whole TTS model every time (see :func:`resynth_segments`).
    """
    from autodub.speech.tts import get_synthesizer
    from autodub.text.translate_hint import annotate_slots, ensure_terminal_punct

    target = get_target(target_key)
    path = _transcript_path(work_dir, target)
    with open(path, encoding="utf-8") as f:
        segments = json.load(f)

    annotate_slots(segments)
    seg = next((s for s in segments if s.get("id") == seg_id), None)
    if seg is None:
        raise EditorError(f"Segment id {seg_id} not found")
    text = ensure_terminal_punct(str(seg.get(target.text_field, "")).strip())
    if not text:
        raise EditorError(f"Segment {seg_id} has no translated text to synthesize")

    # Câu có giọng riêng thì đọc bằng giọng đó — nhưng chỉ khi synth do chính
    # hàm này tạo; synth truyền vào là do nơi gọi đã gom nhóm theo giọng.
    seg_voice = str(seg.get("voice", "")).strip()
    if synth is None and seg_voice:
        voice = seg_voice

    seg_dir = data_path(work_dir, "segments", create_dir=True)
    os.makedirs(seg_dir, exist_ok=True)
    seg_path = seg_wav_path(seg_dir, seg["id"])

    # Clear the previous take first: TTS engines overwrite via os.replace,
    # which fails on Windows while the old file is held open by a player.
    _remove_with_retry(seg_path)

    if synth is None:
        synth = get_synthesizer(target, settings, voice)
        try:
            result = synth.synthesize(
                text=text, output_path=seg_path,
                target_duration=seg.get("slot", seg["duration"]),
            ).to_dict()
        finally:
            # Created here → close here, or the worker subprocesses leak in
            # a long-lived GUI process (GBs of RAM/VRAM per editing session).
            if hasattr(synth, "close"):
                synth.close()
    else:
        result = synth.synthesize(
            text=text, output_path=seg_path,
            target_duration=seg.get("slot", seg["duration"]),
        ).to_dict()

    for stale in _stale_derived_paths(work_dir, target, seg["id"]):
        if os.path.exists(stale):
            _remove_with_retry(stale)
            logger.info(f"Invalidated stale artifact: {os.path.basename(stale)}")

    logger.info(f"Segment {seg_id} re-synthesized "
                f"({result['actual_duration']:.1f}s)")
    return result


def resynth_segments(
    work_dir: str, seg_ids: list[int], settings: Settings,
    target_key: str = "vi", voice: str | None = None,
    reporter: ProgressReporter | None = None,
    on_progress=None,
) -> dict[int, dict]:
    """Re-run TTS for several segments (used by "save all"). Cancellable.

    Strict 1:1 — each requested id renders exactly one clip. The synthesizer
    is created once and shared (a model load per line would dominate
    otherwise).

    ``on_progress(done, total, seg_id)`` fires after each segment finishes —
    a plain callback so GUI workers can emit per-segment signals.
    """
    from autodub.speech.tts import get_synthesizer
    from autodub.speech.tts import voices as voice_catalog

    results: dict[int, dict] = {}
    total = len(seg_ids)
    if not seg_ids:
        return results

    # Gom câu theo giọng thật sự sẽ đọc: câu có khóa "voice" riêng dùng giọng
    # đó, còn lại dùng giọng chung. Mỗi giọng chỉ nạp model MỘT lần.
    target = get_target(target_key)
    path = _transcript_path(work_dir, target)
    with open(path, encoding="utf-8") as f:
        segments = json.load(f)
    voice_of = {s.get("id"): str(s.get("voice", "")).strip() for s in segments}
    main_voice = voice_catalog.resolve(settings, voice)
    by_voice: dict[str, list[int]] = {}
    for seg_id in seg_ids:
        name = voice_catalog.resolve(settings, voice_of.get(seg_id) or voice)
        by_voice.setdefault(name, []).append(seg_id)
    # Giọng chung đi trước để giữ thứ tự tiến độ quen thuộc.
    voice_order = sorted(by_voice, key=lambda n: (n != main_voice, n))

    done = 0
    for name in voice_order:
        ids = by_voice[name]
        # Giọng phụ (vài câu lẻ) chỉ mở một tiến trình con — không nhân
        # đôi RAM theo cả nhóm worker của giọng chung.
        synth = get_synthesizer(
            target, settings, name,
            num_workers=None if name == main_voice else 1)
        try:
            for seg_id in ids:
                if reporter is not None:
                    reporter.check_cancelled()
                    reporter.emit("tts", "progress",
                                  current=done + 1, total=total)
                results[seg_id] = resynth_segment(
                    work_dir, seg_id, settings, target_key, name,
                    synth=synth)
                done += 1
                if on_progress is not None:
                    on_progress(done, total, seg_id)
        finally:
            # Release the worker subprocesses even on error/cancel — leaking
            # a pool per "save all" strands GBs of RAM/VRAM in the GUI
            # process.
            if hasattr(synth, "close"):
                synth.close()
    if reporter is not None and total:
        reporter.emit("tts", "done", current=total, total=total)
    return results


def resolve_existing_background(
    work_dir: str, bg_mode: str, bg_duck_db: float
) -> tuple[str | None, float]:
    """Resolve the background track from artifacts already on disk.

    Never re-runs Demucs: for ``demucs`` it reuses ``no_vocals.wav`` produced by
    the original run (falling back to a silent base if it is absent), for
    ``duck`` it reuses ``original_audio.wav`` at the ducked gain, for ``none`` a
    silent base.
    """
    if bg_mode == "demucs":
        no_vocals = data_path(work_dir, "no_vocals.wav")
        if os.path.exists(no_vocals):
            return no_vocals, 0.0
        logger.warning("no_vocals.wav missing — rebuild will use a silent base")
        return None, 0.0
    if bg_mode == "duck":
        # Prefer the HQ extract (44.1 kHz stereo) when the run produced one.
        for name in ("original_audio_hq.wav", "original_audio.wav"):
            original = data_path(work_dir, name)
            if os.path.exists(original):
                return original, bg_duck_db
        return None, bg_duck_db
    return None, 0.0


def _render_options(state: EditorState, settings: Settings,
                    subtitle_mode: str | None, blur_regions: list[dict] | None,
                    subtitle_style: dict | None) -> tuple[str, list[dict], dict]:
    """Chốt bộ tùy chọn xuất video và ghi lại vào ``render_opts.json``.

    Tham số nào để None thì lấy theo lựa chọn đã lưu của dự án, rồi mới tới
    cài đặt chung — nhờ vậy xuất lại lần nữa cho ra đúng video như lần trước.
    """
    from autodub.media.subtitle import normalize_style

    opts = state.render_opts
    if subtitle_mode is None:
        subtitle_mode = opts.get("subtitle_mode", "none")
    if blur_regions is None:
        blur_regions = opts.get("blur_regions", [])
    style = normalize_style(subtitle_style or opts.get("subtitle_style")
                            or settings.subtitle_style())
    merged = dict(opts)
    merged.update({"subtitle_mode": subtitle_mode,
                   "blur_regions": blur_regions,
                   "subtitle_style": style})
    save_render_opts(state.work_dir, merged)
    return subtitle_mode, blur_regions, style


def _check_render_mode(work_dir: str) -> None:
    """Chặn xuất lại từ bộ giọng đọc tạo theo cơ chế gộp câu đời cũ."""
    from autodub.pipeline import DubPipeline

    seg_dir = data_path(work_dir, "segments")
    if not os.path.isdir(seg_dir):
        return
    marker = os.path.join(seg_dir, ".render_mode")
    mode = None
    if os.path.exists(marker):
        try:
            with open(marker, encoding="utf-8") as f:
                mode = f.read().strip()
        except OSError:
            mode = None
    if mode != DubPipeline.RENDER_MODE and any(
            f.endswith(".wav") for f in os.listdir(seg_dir)):
        raise EditorError(
            "Thư mục này chứa giọng đọc tạo theo cơ chế gộp câu đời cũ. "
            "Hãy chạy tiếp dự án một lần để tạo lại giọng theo từng câu, rồi "
            "mới xuất video.")


def _apply_slowdown(work_dir: str, segments: list[dict],
                    video_path: str | None
                    ) -> tuple[str | None, tuple[float, str] | None]:
    """Đưa mốc thời gian về đúng bản video đã làm chậm, nếu có.

    Lần chạy với Tốc độ video < 1.0 đã tạo ``slowed_video.mp4``. Tệp lời
    thoại trên đĩa vẫn giữ mốc thời gian GỐC, nên ở đây phải co giãn y hệt
    pipeline đã làm và ghép trên bản đã làm chậm — xuất lại sau khi sửa vẫn
    giữ nguyên nhịp phim.

    Trả về ``(video_path, deferred)``. ``deferred`` khác None khi lần chạy
    trước dùng đường GỘP (marker ``deferred_speed.json`` — không có
    ``slowed_video.mp4`` nào trên đĩa): timeline được co giãn theo
    ``1/speed`` và caller phải truyền ``(speed, fps)`` vào ``merge_video``
    để lượt xuất lại cũng làm chậm ngay trong lượt mã hóa.
    """
    from autodub.text.translate_hint import annotate_slots

    annotate_slots(segments)
    deferred_marker = data_path(work_dir, "deferred_speed.json")
    if os.path.isfile(deferred_marker):
        from autodub.media.retime import rescale_segments
        try:
            with open(deferred_marker, encoding="utf-8") as f:
                info = json.load(f)
            speed, fps = float(info["speed"]), str(info["fps"])
            if speed < 0.999:
                rescale_segments(segments, 1.0 / speed)
                annotate_slots(segments)
                logger.info(f"Làm chậm video ({speed}x) gộp vào lượt xuất — "
                            "như lần chạy trước")
                return video_path, (speed, fps)
        except (OSError, ValueError, KeyError) as e:
            logger.warning(f"Không đọc được deferred_speed.json ({e}) — "
                           "xuất trên video gốc")
        return video_path, None
    slowed_video = data_path(work_dir, "slowed_video.mp4")
    slowed_marker = data_path(work_dir, "slowed_video.json")
    if not (os.path.isfile(slowed_video) and os.path.isfile(slowed_marker)):
        return video_path, None
    from autodub.media.retime import (probe_duration, probe_video_info,
                                      rescale_segments)
    try:
        orig_dur = probe_video_info(video_path)[0] if video_path else None
        new_dur = probe_duration(slowed_video)
        if orig_dur and new_dur:
            rescale_segments(segments, new_dur / orig_dur)
            annotate_slots(segments)
            logger.info(f"Dùng bản video đã làm chậm ({new_dur:.0f} giây) từ "
                        "lần chạy trước")
            return slowed_video, None
    except Exception as e:
        logger.warning(f"Không dùng được bản video đã làm chậm ({e}) — "
                       "xuất trên video gốc")
    return video_path, None


def final_segments_dir(work_dir: str) -> str:
    """Thư mục chứa bản giọng đọc CUỐI CÙNG đã có trên đĩa.

    Mốc chữ của phụ đề kiểu cụm chữ phải tính trên đúng đoạn âm thanh mà
    người xem nghe được, nên phải chọn thư mục dẫn xuất mới nhất chứ không
    phải bản thô.
    """
    root = data_dir(work_dir)
    if os.path.isdir(root):
        speed_dirs = sorted(d for d in os.listdir(root)
                            if d.startswith("segments_speed"))
        for name in ("segments_timed", *reversed(speed_dirs),
                     "segments_post", "segments"):
            path = os.path.join(root, name)
            if os.path.isdir(path) and any(f.endswith(".wav")
                                           for f in os.listdir(path)):
                return path
    return data_path(work_dir, "segments")


def rebuild_output(
    work_dir: str, settings: Settings, target_key: str = "vi",
    voice: str | None = None, bg_mode: str = "demucs", bg_duck_db: float = -12.0,
    subtitle_mode: str | None = None, blur_regions: list[dict] | None = None,
    subtitle_style: dict | None = None,
    reporter: ProgressReporter | None = None,
) -> str:
    """Dựng lại âm thanh và video từ danh sách câu hiện tại.

    Dùng lại các đoạn giọng đọc đã có; chỉ chạy lại phần đặt lại thời điểm,
    trộn âm thanh và ghép video. Muốn ĐỔI CHỮ trên phụ đề mà không đụng tới
    giọng đọc thì dùng :func:`rebuild_subtitles` — nhanh hơn nhiều.
    """
    from autodub.media.audio import merge_segments, wav_duration_s
    from autodub.media.video import merge_video
    from autodub.text.subtitles import refresh_subtitles

    del voice        # giọng chỉ dùng khi đọc lại, không ảnh hưởng bước ghép

    state = load_work_dir(work_dir, target_key)
    target, segments = state.target, state.segments
    subtitle_mode, blur_regions, style = _render_options(
        state, settings, subtitle_mode, blur_regions, subtitle_style)

    def emit(step, status, **kw):
        if reporter is not None:
            reporter.emit(step, status, **kw)

    def check():
        if reporter is not None:
            reporter.check_cancelled()

    check()
    emit("merge_audio", "start")
    seg_dir = data_path(work_dir, "segments")
    _check_render_mode(work_dir)
    video_path, deferred_speed = _apply_slowdown(work_dir, segments,
                                                 state.video_path)
    slowed_video = data_path(work_dir, "slowed_video.mp4")

    total_duration = max(s["end"] for s in segments) + 1.0 if segments else 0.0
    merge_dir = seg_dir
    if settings.voice_postprocess:
        from autodub.media.audio import postprocess_voice_clips
        merge_dir = postprocess_voice_clips(
            segments, seg_dir, data_path(work_dir, "segments_post"),
            target_lufs=settings.voice_target_lufs)
    if abs(settings.voice_speed - 1.0) >= 0.005:
        from autodub.media.audio import slow_segments
        speed = settings.voice_speed
        dst = data_path(work_dir,
                        f"segments_speed{speed:.2f}".replace(".", "_"))
        merge_dir = slow_segments(segments, merge_dir, dst, speed)
    if settings.soft_timing_fit:
        # Cùng cơ chế với pipeline: dồn trễ vào khoảng lặng, không đổi tốc độ
        # đọc từng câu.
        from autodub.media.timing import apply_soft_timing
        merge_dir, _timing = apply_soft_timing(
            segments, merge_dir, data_path(work_dir, "segments_timed"),
            settings)
    for s in segments:
        dur = wav_duration_s(seg_wav_path(merge_dir, s["id"]))
        if dur:
            total_duration = max(total_duration, s["start"] + dur + 0.5)

    background_path, background_gain_db = resolve_existing_background(
        work_dir, bg_mode, bg_duck_db)
    slowed_bg = data_path(work_dir, "slowed_background.wav")
    # Nhạc nền đã làm chậm khi video chậm — dù chậm rời (slowed_video.mp4)
    # hay gộp vào lượt xuất (deferred_speed).
    if ((video_path == slowed_video or deferred_speed is not None)
            and os.path.isfile(slowed_bg)):
        background_path = slowed_bg
    merged_audio_path = data_path(work_dir, target.audio_name)
    merge_segments(
        segments, merge_dir, merged_audio_path, total_duration,
        background_path=background_path, background_gain_db=background_gain_db,
        duck_voice_db=settings.bg_duck_voice_db)
    emit("merge_audio", "done", detail=merged_audio_path)

    check()
    if not video_path:
        raise EditorError("Thư mục dự án không còn video gốc nên không ghép "
                          "lại được. Hãy chọn lại tệp video rồi chạy tiếp.")
    emit("merge_video", "start")
    dubbed = os.path.join(work_dir, "dubbed_video.mp4")
    # Phụ đề luôn được sinh lại từ danh sách câu hiện tại, trên đúng timeline
    # vừa đặt — chữ trong video là chữ bạn vừa sửa, không phải bản cũ.
    _srt_path, burn_path = refresh_subtitles(
        segments, work_dir, target, style, merge_dir=merge_dir,
        settings=settings, for_burn=subtitle_mode == "burn")
    merge_video(
        video_path, merged_audio_path, dubbed,
        srt_path=burn_path, subtitle_mode=subtitle_mode,
        blur_regions=blur_regions, subtitle_lang=target.iso639_2,
        subtitle_style=style,
        speed=deferred_speed[0] if deferred_speed else None,
        fps=deferred_speed[1] if deferred_speed else None)
    emit("merge_video", "done", detail=dubbed)
    emit("done", "done", detail=work_dir)
    logger.info(f"Đã xuất xong video: {dubbed}")
    return dubbed


def rebuild_subtitles(
    work_dir: str, settings: Settings, target_key: str = "vi",
    subtitle_mode: str | None = None, blur_regions: list[dict] | None = None,
    subtitle_style: dict | None = None,
    reporter: ProgressReporter | None = None,
) -> str:
    """Ghi lại PHỤ ĐỀ vào video, giữ nguyên phần âm thanh đã có.

    Đây là đường đi cho việc sửa phụ đề: chữ và kiểu chữ bạn vừa đổi được
    ghi thẳng vào chính tệp video kết quả, không đọc lại giọng, không trộn
    lại âm thanh và tuyệt đối không phải chạy lại cả quy trình. Cần bản âm
    thanh của lần xuất trước — chưa có thì dùng :func:`rebuild_output`.
    """
    from autodub.media.video import merge_video
    from autodub.text.subtitles import refresh_subtitles

    state = load_work_dir(work_dir, target_key)
    target, segments = state.target, state.segments
    subtitle_mode, blur_regions, style = _render_options(
        state, settings, subtitle_mode, blur_regions, subtitle_style)

    merged_audio_path = data_path(work_dir, target.audio_name)
    if not os.path.isfile(merged_audio_path):
        raise EditorError(
            "Dự án này chưa có bản âm thanh đã ghép nên chưa ghi riêng phụ đề "
            "được. Hãy bấm Xuất video một lần trước đã.")

    video_path, deferred_speed = _apply_slowdown(work_dir, segments,
                                                 state.video_path)
    if not video_path:
        raise EditorError("Thư mục dự án không còn video gốc nên không ghép "
                          "lại được. Hãy chọn lại tệp video rồi chạy tiếp.")

    if reporter is not None:
        reporter.check_cancelled()
        reporter.emit("merge_video", "start")

    _srt_path, burn_path = refresh_subtitles(
        segments, work_dir, target, style,
        merge_dir=final_segments_dir(work_dir), settings=settings,
        for_burn=subtitle_mode == "burn")

    dubbed = os.path.join(work_dir, "dubbed_video.mp4")
    merge_video(
        video_path, merged_audio_path, dubbed,
        srt_path=burn_path, subtitle_mode=subtitle_mode,
        blur_regions=blur_regions, subtitle_lang=target.iso639_2,
        subtitle_style=style,
        speed=deferred_speed[0] if deferred_speed else None,
        fps=deferred_speed[1] if deferred_speed else None)
    if reporter is not None:
        reporter.emit("merge_video", "done", detail=dubbed)
        reporter.emit("done", "done", detail=work_dir)
    logger.info(f"Đã ghi lại phụ đề vào video: {dubbed}")
    return dubbed


def render_segment_preview(
    work_dir: str, settings: Settings, seg_id: int, target_key: str = "vi",
    bg_mode: str = "demucs", bg_duck_db: float = -12.0,
    subtitle_mode: str | None = None, subtitle_style: dict | None = None,
    pad_s: float = 1.0,
) -> str:
    """Dựng một đoạn XEM THỬ ngắn quanh câu ``seg_id``, trước khi xuất cả phim.

    Xuất cả video để nghe thử một câu là quá đắt. Đường đi này chỉ cắt vài
    giây video quanh câu đang chọn, trộn giọng đọc + nhạc nền của đúng khoảng
    đó rồi mã hóa nhanh (ultrafast, tối đa 480 điểm ảnh) — vài giây là có
    tệp xem được.

    Giọng đọc lấy từ bản dẫn xuất CUỐI CÙNG đã có trên đĩa (đã hậu kỳ, đã
    giãn nhịp — nếu dự án từng xuất); dự án chưa xuất lần nào thì dùng bản
    thô, sai khác chút ít so với bản xuất thật. Phụ đề xem thử luôn là kiểu
    cả câu (kiểu cụm chữ chỉ có ở bản xuất thật).

    Trả về đường dẫn tệp mp4 xem thử trong thư mục data của dự án.
    """
    from autodub.media.audio import merge_segments, wav_duration_s
    from autodub.media.video import render_preview_clip
    from autodub.text.srt import generate_srt_styled
    from autodub.utils import ffmpeg_timeout_s

    state = load_work_dir(work_dir, target_key)
    target, segments = state.target, state.segments
    subtitle_mode, _blur, style = _render_options(
        state, settings, subtitle_mode, None, subtitle_style)

    seg = next((s for s in segments if s.get("id") == seg_id), None)
    if seg is None:
        raise EditorError(f"Không tìm thấy câu số {seg_id} trong dự án.")

    _check_render_mode(work_dir)
    # Cùng phép co giãn timeline với lượt xuất thật — dự án có làm chậm video
    # thì mốc câu đã được đổi về timeline chậm, còn deferred trả (speed, fps)
    # để làm chậm ngay trong lượt mã hóa xem thử.
    video_path, deferred_speed = _apply_slowdown(work_dir, segments,
                                                 state.video_path)
    if not video_path:
        raise EditorError("Thư mục dự án không còn video gốc nên không dựng "
                          "được đoạn xem thử. Hãy chọn lại tệp video.")
    seg = next(s for s in segments if s.get("id") == seg_id)

    merge_dir = final_segments_dir(work_dir)
    voice_dur = wav_duration_s(seg_wav_path(merge_dir, seg_id)) or 0.0
    w0 = max(0.0, float(seg["start"]) - pad_s)
    w1 = max(float(seg["end"]),
             float(seg["start"]) + voice_dur) + pad_s

    # Các câu chạm vào cửa sổ xem thử, mốc thời gian dời về 0 tại w0. Giọng
    # của câu tràn vào từ trước cửa sổ vẫn được trộn (mốc âm được
    # merge_segments cắt đúng phần lọt trong khối); riêng phụ đề thì kẹp về 0.
    window = [dict(s, start=float(s["start"]) - w0, end=float(s["end"]) - w0)
              for s in segments
              if float(s["end"]) > w0 and float(s["start"]) < w1]
    sub_window = [dict(s, start=max(0.0, s["start"]), end=min(s["end"], w1 - w0))
                  for s in window]

    background_path, background_gain_db = resolve_existing_background(
        work_dir, bg_mode, bg_duck_db)
    slowed_bg = data_path(work_dir, "slowed_background.wav")
    if ((video_path == data_path(work_dir, "slowed_video.mp4")
         or deferred_speed is not None) and os.path.isfile(slowed_bg)):
        background_path = slowed_bg

    # Cắt nhạc nền về đúng cửa sổ để merge_segments không phải trộn từ 0s.
    bg_cut = None
    if background_path and os.path.isfile(background_path):
        import subprocess
        bg_cut = data_path(work_dir, "preview_bg.tmp.wav")
        result = subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{w0:.3f}", "-to", f"{w1:.3f}",
             "-i", background_path, "-acodec", "pcm_s16le", bg_cut],
            capture_output=True, text=True,
            timeout=ffmpeg_timeout_s(w1 - w0))
        if result.returncode != 0 or not os.path.getsize(bg_cut):
            logger.warning("Không cắt được nhạc nền cho đoạn xem thử — "
                           "dùng nền im lặng")
            bg_cut = None

    preview_audio = data_path(work_dir, "preview_audio.tmp.wav")
    preview_path = data_path(work_dir, f"preview_seg{seg_id:05d}.mp4")
    srt_tmp = None
    try:
        merge_segments(window, merge_dir, preview_audio, w1 - w0,
                       background_path=bg_cut,
                       background_gain_db=background_gain_db,
                       duck_voice_db=settings.bg_duck_voice_db)
        if subtitle_mode == "burn":
            srt_tmp = data_path(work_dir, "preview_subs.tmp.srt")
            generate_srt_styled(sub_window, srt_tmp, target.text_field, style)

        # Cửa sổ tính trên timeline ĐÃ làm chậm; đường deferred cắt trên tệp
        # nguồn (timeline gốc) rồi làm chậm trong chính lượt mã hóa này.
        speed = deferred_speed[0] if deferred_speed else None
        fps = deferred_speed[1] if deferred_speed else None
        vs0, vs1 = (w0 * speed, w1 * speed) if speed else (w0, w1)
        render_preview_clip(video_path, preview_audio, preview_path,
                            vs0, vs1, srt_path=srt_tmp, subtitle_style=style,
                            speed=speed, fps=fps)
    finally:
        for tmp in (preview_audio, bg_cut, srt_tmp):
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    logger.info(f"Đã dựng đoạn xem thử câu {seg_id}: {preview_path}")
    return preview_path


# ---------------------------------------------------------------------------
# Sửa cấu trúc câu thoại: thêm, xóa, tách, gộp và đổi mốc thời gian.
#
# Năm hàm dưới đây đổi số lượng hoặc thứ tự câu, nên sau mỗi lần gọi chúng đều
# phải làm ba việc bắt buộc:
#   1. Đánh lại số thứ tự câu liên tục từ 1 tới N.
#   2. Đổi tên tệp giọng đọc trong data/segments/ cho khớp số mới.
#   3. Xóa mọi tệp dẫn xuất đã sinh từ bộ câu cũ.
# Bỏ bước nào cũng dẫn tới hậu quả nặng: lần xuất video sau sẽ ghép nhầm
# giọng của câu này vào chỗ của câu khác.
# ---------------------------------------------------------------------------

_MIN_SEGMENT_S = 0.2        # câu ngắn hơn mức này thì nghe như tiếng động
_TIME_EPSILON = 1e-6        # sai số cho phép khi so hai mốc thời gian

# Thư mục chứa các bản giọng đọc đã qua xử lý, phải xóa khi bộ câu đổi
_DERIVED_DIR_PREFIXES = ("segments_speed", "segments_slow", "segments_fit",
                         "segments_post", "segments_timed")


def _segments_dir(work_dir: str) -> str:
    """Thư mục chứa tệp giọng đọc của từng câu."""
    return data_path(work_dir, "segments")


def _load_segments(work_dir: str, target: TargetLang) -> tuple[list[dict], str]:
    """Đọc danh sách câu thoại và trả về kèm đường dẫn tệp."""
    path = _transcript_path(work_dir, target)
    if not os.path.exists(path):
        raise EditorError(
            f"Chưa có bản dịch trong thư mục dự án này ({target.transcript_name}). "
            "Hãy chạy lồng tiếng trước khi chỉnh sửa.")
    with open(path, encoding="utf-8") as f:
        segments = json.load(f)
    if not isinstance(segments, list) or not segments:
        raise EditorError("Danh sách câu thoại trống hoặc sai định dạng.")
    return segments, path


def _index_of(segments: list[dict], seg_id: int) -> int:
    """Vị trí của một câu trong danh sách, không có thì báo lỗi rõ ràng."""
    for index, segment in enumerate(segments):
        if segment.get("id") == seg_id:
            return index
    raise EditorError(f"Không tìm thấy câu số {seg_id} trong dự án này.")


def _validate_times(start: float, end: float, label: str = "") -> None:
    """Kiểm tra một khoảng thời gian có hợp lệ không."""
    prefix = f"{label}: " if label else ""
    if start < -_TIME_EPSILON:
        raise EditorError(f"{prefix}thời điểm bắt đầu không được là số âm.")
    if end - start < _MIN_SEGMENT_S - _TIME_EPSILON:
        raise EditorError(
            f"{prefix}câu thoại phải dài ít nhất {_MIN_SEGMENT_S} giây. "
            "Hãy kéo dài thêm hoặc gộp với câu bên cạnh.")


def _check_no_overlap(segments: list[dict], index: int,
                      start: float, end: float) -> None:
    """Câu này có lấn sang câu trước hoặc câu sau không."""
    if index > 0:
        previous = segments[index - 1]
        if start < float(previous.get("end", 0.0)) - _TIME_EPSILON:
            raise EditorError(
                "Câu này bắt đầu trước khi câu liền trước kết thúc. "
                "Hãy kéo mốc bắt đầu sang phải, hoặc gộp hai câu lại.")
    if index < len(segments) - 1:
        following = segments[index + 1]
        if end > float(following.get("start", 0.0)) + _TIME_EPSILON:
            raise EditorError(
                "Câu này kết thúc sau khi câu liền sau đã bắt đầu. "
                "Hãy kéo mốc kết thúc sang trái, hoặc gộp hai câu lại.")


def _renumber_and_rename(work_dir: str, segments: list[dict],
                         old_ids: list[int]) -> None:
    """Đánh lại số câu từ 1 tới N và đổi tên tệp giọng đọc cho khớp.

    `old_ids` là số cũ của từng câu theo đúng thứ tự hiện tại của danh sách;
    dùng -1 cho câu mới chưa có tệp giọng đọc nào.
    """
    seg_dir = _segments_dir(work_dir)
    renames: list[tuple[str, str]] = []
    for position, (segment, old_id) in enumerate(zip(segments, old_ids), start=1):
        segment["id"] = position
        if old_id < 0 or old_id == position or not os.path.isdir(seg_dir):
            continue
        source = seg_wav_path(seg_dir, old_id)
        if os.path.isfile(source):
            renames.append((source,
                            os.path.join(seg_dir, f"seg_{position:05d}.wav")))
    _apply_renames(renames)


def _apply_renames(renames: list[tuple[str, str]]) -> None:
    """Đổi tên hàng loạt qua tên tạm, tránh hai tệp đè lên nhau giữa chừng."""
    staged: list[tuple[str, str]] = []
    for source, target_path in renames:
        temporary = target_path + ".doi_ten_tam"
        try:
            os.replace(source, temporary)
            staged.append((temporary, target_path))
        except OSError as e:
            logger.warning(f"Không đổi tên được {source}: {e}")
    for temporary, target_path in staged:
        try:
            os.replace(temporary, target_path)
        except OSError as e:
            logger.warning(f"Không đặt lại tên {target_path}: {e}")


def _drop_segment_audio(work_dir: str, seg_id: int) -> None:
    """Xóa tệp giọng đọc của một câu đã bị bỏ."""
    seg_dir = _segments_dir(work_dir)
    if not os.path.isdir(seg_dir):
        return
    path = seg_wav_path(seg_dir, seg_id)
    if os.path.isfile(path):
        _remove_with_retry(path)


def _invalidate_derived(work_dir: str, target: TargetLang) -> None:
    """Xóa mọi thứ đã dựng từ bộ câu cũ để lần xuất sau làm lại từ đầu."""
    import shutil

    for path in (data_path(work_dir, target.audio_name),
                 os.path.join(work_dir, "dubbed_video.mp4")):
        if os.path.isfile(path):
            _remove_with_retry(path)
    root = data_dir(work_dir)
    if not os.path.isdir(root):
        return
    for name in os.listdir(root):
        if name.startswith(_DERIVED_DIR_PREFIXES):
            try:
                shutil.rmtree(os.path.join(root, name))
            except OSError as e:
                logger.warning(f"Không xóa được thư mục {name}: {e}")


def _commit(work_dir: str, target: TargetLang, segments: list[dict],
            path: str, old_ids: list[int]) -> None:
    """Đánh số lại, đổi tên tệp, xóa tệp dẫn xuất rồi ghi xuống đĩa."""
    _renumber_and_rename(work_dir, segments, old_ids)
    _invalidate_derived(work_dir, target)
    save_json_atomic(segments, path)


def add_segment(work_dir: str, after_id: int, start: float, end: float,
                text: str = "", source_text: str = "",
                target_key: str = "vi") -> int:
    """Chèn một câu mới ngay sau câu `after_id`.

    Dùng `after_id` bằng 0 để chèn lên đầu danh sách. Trả về số thứ tự của
    câu vừa tạo sau khi cả danh sách được đánh số lại.
    """
    target = get_target(target_key)
    segments, path = _load_segments(work_dir, target)
    _validate_times(float(start), float(end), "Câu mới")

    position = 0 if after_id in (0, None) else _index_of(segments, after_id) + 1
    fresh = {
        "id": -1,
        "start": float(start),
        "end": float(end),
        "duration": round(float(end) - float(start), 3),
        "text": source_text or "",
        target.text_field: (text or "").strip(),
    }
    old_ids = [int(s.get("id", -1)) for s in segments]
    segments.insert(position, fresh)
    old_ids.insert(position, -1)
    _check_no_overlap(segments, position, float(start), float(end))

    _commit(work_dir, target, segments, path, old_ids)
    new_id = int(segments[position]["id"])
    logger.info(f"Đã thêm câu mới số {new_id} vào {work_dir}")
    return new_id


def delete_segment(work_dir: str, seg_id: int, target_key: str = "vi") -> None:
    """Xóa một câu cùng tệp giọng đọc của nó."""
    target = get_target(target_key)
    segments, path = _load_segments(work_dir, target)
    if len(segments) <= 1:
        raise EditorError(
            "Dự án phải còn ít nhất một câu thoại. Hãy sửa nội dung câu này "
            "thay vì xóa nó đi.")
    index = _index_of(segments, seg_id)
    old_ids = [int(s.get("id", -1)) for s in segments]

    _drop_segment_audio(work_dir, seg_id)
    segments.pop(index)
    old_ids.pop(index)
    _commit(work_dir, target, segments, path, old_ids)
    logger.info(f"Đã xóa câu số {seg_id} khỏi {work_dir}")


def _split_text(text: str, ratio: float) -> tuple[str, str]:
    """Chia một đoạn chữ theo tỉ lệ, cắt ở ranh giới từ gần nhất."""
    text = (text or "").strip()
    if not text:
        return "", ""
    words = text.split()
    if len(words) < 2:
        return text, ""
    cut = max(1, min(len(words) - 1, round(len(words) * ratio)))
    return " ".join(words[:cut]), " ".join(words[cut:])


def split_segment(work_dir: str, seg_id: int, at_time: float,
                  target_key: str = "vi") -> tuple[int, int]:
    """Tách một câu thành hai tại mốc thời gian `at_time`.

    Phần chữ được chia theo tỉ lệ thời gian, cắt ở ranh giới từ gần nhất để
    không đứt đôi một chữ. Trả về số thứ tự của câu trái và câu phải.
    """
    target = get_target(target_key)
    segments, path = _load_segments(work_dir, target)
    index = _index_of(segments, seg_id)
    segment = segments[index]
    start = float(segment.get("start", 0.0))
    end = float(segment.get("end", 0.0))
    at_time = float(at_time)

    if not (start + _MIN_SEGMENT_S <= at_time <= end - _MIN_SEGMENT_S):
        raise EditorError(
            "Chỗ tách nằm quá sát đầu hoặc cuối câu. Mỗi nửa phải dài ít "
            f"nhất {_MIN_SEGMENT_S} giây.")

    ratio = (at_time - start) / (end - start) if end > start else 0.5
    left_text, right_text = _split_text(
        str(segment.get(target.text_field, "")), ratio)
    left_source, right_source = _split_text(str(segment.get("text", "")), ratio)

    left = dict(segment)
    left.update({"end": at_time, "duration": round(at_time - start, 3),
                 target.text_field: left_text, "text": left_source})
    right = dict(segment)
    right.update({"start": at_time, "duration": round(end - at_time, 3),
                  target.text_field: right_text, "text": right_source})

    old_ids = [int(s.get("id", -1)) for s in segments]
    # Cả hai nửa đều phải đọc lại vì lời thoại đã khác, nên bỏ tệp giọng cũ.
    _drop_segment_audio(work_dir, seg_id)
    segments[index:index + 1] = [left, right]
    old_ids[index:index + 1] = [-1, -1]

    _commit(work_dir, target, segments, path, old_ids)
    left_id = int(segments[index]["id"])
    right_id = int(segments[index + 1]["id"])
    logger.info(f"Đã tách câu số {seg_id} thành {left_id} và {right_id} "
                f"tại giây {at_time:.3f}")
    return left_id, right_id


def merge_segments(work_dir: str, seg_ids: list[int],
                   target_key: str = "vi") -> int:
    """Gộp nhiều câu liền nhau thành một câu duy nhất.

    Mốc bắt đầu lấy của câu đầu, mốc kết thúc lấy của câu cuối, phần chữ nối
    lại bằng dấu cách. Trả về số thứ tự của câu còn lại sau khi gộp.
    """
    target = get_target(target_key)
    segments, path = _load_segments(work_dir, target)
    ids = sorted({int(i) for i in seg_ids})
    if len(ids) < 2:
        raise EditorError("Hãy chọn ít nhất hai câu liền nhau để gộp.")

    positions = [_index_of(segments, seg_id) for seg_id in ids]
    if positions != list(range(positions[0], positions[0] + len(positions))):
        raise EditorError(
            "Chỉ gộp được những câu nằm liền nhau. Hãy chọn lại các câu "
            "kề nhau rồi thử lần nữa.")

    first, last = positions[0], positions[-1]
    group = segments[first:last + 1]
    merged = dict(group[0])
    merged["end"] = float(group[-1].get("end", 0.0))
    merged["duration"] = round(merged["end"] - float(merged.get("start", 0.0)), 3)
    merged[target.text_field] = " ".join(
        str(s.get(target.text_field, "")).strip() for s in group).strip()
    merged["text"] = " ".join(
        str(s.get("text", "")).strip() for s in group).strip()

    old_ids = [int(s.get("id", -1)) for s in segments]
    for seg_id in ids:
        _drop_segment_audio(work_dir, seg_id)
    segments[first:last + 1] = [merged]
    old_ids[first:last + 1] = [-1]        # câu gộp phải được đọc lại

    _commit(work_dir, target, segments, path, old_ids)
    kept = int(segments[first]["id"])
    logger.info(f"Đã gộp {len(ids)} câu thành câu số {kept} trong {work_dir}")
    return kept


def set_segment_time(work_dir: str, seg_id: int, start: float, end: float,
                     target_key: str = "vi") -> None:
    """Đổi mốc bắt đầu và kết thúc của một câu.

    Dùng khi người dùng kéo khối câu thoại trên dải thời gian.
    """
    target = get_target(target_key)
    segments, path = _load_segments(work_dir, target)
    index = _index_of(segments, seg_id)
    start, end = float(start), float(end)
    _validate_times(start, end, f"Câu {seg_id}")
    _check_no_overlap(segments, index, start, end)

    segment = segments[index]
    if (abs(float(segment.get("start", 0.0)) - start) < _TIME_EPSILON
            and abs(float(segment.get("end", 0.0)) - end) < _TIME_EPSILON):
        return
    segment["start"] = start
    segment["end"] = end
    segment["duration"] = round(end - start, 3)

    # Chỉ đổi mốc thời gian nên không cần đánh số lại, nhưng bản ghép và
    # video cũ đã sai thời điểm nên phải bỏ đi.
    _invalidate_derived(work_dir, target)
    save_json_atomic(segments, path)
    logger.info(f"Đã đổi mốc thời gian câu số {seg_id} thành "
                f"{start:.3f} tới {end:.3f} giây")


# --- Lịch sử bản xuất -------------------------------------------------------
# Giữ tối đa 3 bản dubbed_video gần nhất trong data/export_history/ để người
# dùng có thể quay lại bản cũ nếu lần xuất mới có vấn đề.
_EXPORT_HISTORY_DIR = "export_history"
_MAX_HISTORY = 3


def record_export_snapshot(work_dir: str) -> None:
    """Chụp bản dubbed_video.mp4 hiện tại vào lịch sử trước khi xuất đè.

    Gọi SAU khi lần xuất mới thành công — snapshot là bản vừa tạo ra, không
    phải bản đang sắp bị ghi đè (giữ bản tốt nhất, không phải bản sắp mất).
    Hỏng thì bỏ qua vì đây chỉ là tiện ích phụ.
    """
    import shutil
    import time

    src = os.path.join(work_dir, "dubbed_video.mp4")
    if not os.path.isfile(src):
        return
    try:
        hist_dir = data_path(work_dir, _EXPORT_HISTORY_DIR, create_dir=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        dst = os.path.join(hist_dir, f"dubbed_{stamp}.mp4")
        shutil.copy2(src, dst)
        _prune_history(hist_dir)
    except OSError:
        pass


def _prune_history(hist_dir: str) -> None:
    """Xóa bớt, chỉ giữ _MAX_HISTORY bản mới nhất."""
    try:
        entries = sorted([
            f for f in os.listdir(hist_dir)
            if f.startswith("dubbed_") and f.endswith(".mp4")
        ])
        for old in entries[:-_MAX_HISTORY]:
            try:
                os.remove(os.path.join(hist_dir, old))
            except OSError:
                pass
    except OSError:
        pass


def list_export_history(work_dir: str) -> list[dict]:
    """Danh sách bản xuất đã lưu, mới nhất trước.

    Mỗi phần tử: {"path": ..., "name": ..., "mtime": ..., "size_bytes": ...}.
    """
    try:
        hist_dir = data_path(work_dir, _EXPORT_HISTORY_DIR)
        if not os.path.isdir(hist_dir):
            return []
        entries = []
        for f in os.listdir(hist_dir):
            if f.startswith("dubbed_") and f.endswith(".mp4"):
                p = os.path.join(hist_dir, f)
                try:
                    st = os.stat(p)
                    entries.append({
                        "path": p,
                        "name": f,
                        "mtime": st.st_mtime,
                        "size_bytes": st.st_size,
                    })
                except OSError:
                    pass
        entries.sort(key=lambda x: x["mtime"], reverse=True)
        return entries
    except OSError:
        return []
