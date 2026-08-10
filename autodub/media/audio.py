"""Audio processing: extraction from video, uniform voice speed, dub mixing."""
import os
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor

from pydub import AudioSegment

from autodub.resources import FFMPEG_SLOTS
from autodub.utils import setup_logging, ensure_dir, ffmpeg_timeout_s, seg_wav_path

logger = setup_logging("autodub.audio")


class FallbackCounter:
    """Sổ ghi các câu phải dùng bản dự phòng, an toàn đa luồng.

    Các nhánh fallback ở đây (atempo lỗi → giữ clip tốc độ gốc, hậu kỳ lỗi →
    giữ clip thô) là CỐ Ý: thiếu clip thì các bước sau hiểu là "câu mất" và
    video câm hẳn đoạn đó, tệ hơn hẳn một câu sai tốc độ. Nhưng nuốt im lặng
    thì người dùng nghe thấy chất lượng tệ mà không biết vì sao. Đếm ở đây rồi
    đưa lên ``quality_report.json`` làm chuyện đó giải thích được.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, list] = {}

    def reset(self) -> None:
        with self._lock:
            self._events.clear()

    def add(self, kind: str, seg_id) -> None:
        with self._lock:
            self._events.setdefault(kind, []).append(seg_id)

    def snapshot(self) -> dict[str, list]:
        with self._lock:
            return {k: list(v) for k, v in self._events.items()}


#: Sổ chung cho cả lượt chạy — pipeline reset cùng chỗ với ``USAGE``.
FALLBACKS = FallbackCounter()


def _seg_id_from_path(path: str):
    """Số câu suy từ tên tệp ``seg_00012.wav``, hoặc chính tên tệp nếu lạ."""
    name = os.path.splitext(os.path.basename(path))[0]
    digits = name.rpartition("_")[2]
    return int(digits) if digits.isdigit() else name

# Trần thời gian cho ffmpeg trên MỘT segment (vài giây audio) — 120 s là
# rộng rãi gấp trăm lần bình thường; quá mức đó chắc chắn là treo.
_SEG_TIMEOUT_S = 120

# Parallel ffmpeg workers for per-segment filters. Threads (not processes):
# the GIL is released while subprocess.run waits. Leave one core for the GUI
# and the TTS workers — beyond that, Windows process-creation overhead and
# core contention eat the gains anyway.
_FFMPEG_WORKERS = max(2, min(6, (os.cpu_count() or 4) - 1))

# Dub voices render at 24 kHz but the 16 kHz ASR-rate background used to
# drag the whole mix down to 16 kHz. Mix at least at this rate instead.
_MIN_MERGE_RATE = 44100

# Streaming merge block length — one block is the peak RAM of the mixer.
_MERGE_BLOCK_S = 60

# Ducking ramp: thời gian nhạc nền trượt xuống/lên quanh mỗi câu nói.
# 120 ms đủ mượt để không nghe "hụt" nhạc mà vẫn kịp nhường chỗ cho giọng.
_DUCK_RAMP_S = 0.12


def apply_atempo(src: str, dst: str, speed: float) -> bool:
    """Time-compress/stretch an audio file with ffmpeg atempo.

    ``src`` and ``dst`` may be the same path (ffmpeg cannot edit in place, so
    a temp file is used). Returns True on success; on failure the source is
    left as the result and False is returned.
    """
    tmp = dst + ".atempo.tmp.wav"
    try:
        with FFMPEG_SLOTS:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", src,
                 "-filter:a", f"atempo={speed:.3f}", tmp],
                capture_output=True, text=True, timeout=_SEG_TIMEOUT_S,
            )
        failed = (result.returncode != 0 or not os.path.exists(tmp)
                  or os.path.getsize(tmp) == 0)
        err = result.stderr[:200] if failed else ""
    except subprocess.TimeoutExpired:
        failed, err = True, f"ffmpeg treo quá {_SEG_TIMEOUT_S}s"
    if failed:
        logger.error(f"atempo {speed:.2f}x failed on {src}: {err}")
        FALLBACKS.add("atempo_failed", _seg_id_from_path(src))
        if os.path.exists(tmp):
            os.remove(tmp)
        if src != dst:
            shutil.copyfile(src, dst)
        return False
    os.replace(tmp, dst)
    return True


def extract_audio(video_path: str, output_path: str, sample_rate: int = 16000,
                  channels: int = 1) -> str:
    """Extract PCM audio from a video file at the given rate/channel layout.

    Two call sites, two profiles: 16 kHz mono for ASR (what Whisper wants),
    44.1 kHz stereo for the background/mix path (``hq_background``) so the
    soundtrack keeps its top octaves instead of being crushed to phone-call
    bandwidth before Demucs ever sees it.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")

    cmd = [
        "ffmpeg", "-i", video_path,
        "-vn",
        "-ar", str(sample_rate),
        "-ac", str(channels),
        "-acodec", "pcm_s16le",
        "-y",
        output_path,
    ]

    logger.info(f"Extracting audio: {video_path} → {output_path}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=ffmpeg_timeout_s(None))
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"FFmpeg treo khi tách audio từ {video_path}")
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {result.stderr}")

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError(f"Audio extraction produced empty file: {output_path}")

    logger.info(f"Audio extracted: {output_path} ({os.path.getsize(output_path)} bytes)")
    return output_path


def extract_audio_dual(video_path: str, asr_path: str, hq_path: str,
                       asr_rate: int = 16000) -> None:
    """Rút CẢ HAI bản audio (16 kHz mono ASR + 44.1 kHz stereo nền) trong
    MỘT lệnh ffmpeg — video chỉ bị giải mã một lần thay vì hai.

    Lỗi thì xoá file dở dang và ném lên; lớp gọi tự rơi về hai lệnh rời.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-ar", str(asr_rate), "-ac", "1", "-acodec", "pcm_s16le",
        asr_path,
        "-vn", "-ar", "44100", "-ac", "2", "-acodec", "pcm_s16le",
        hq_path,
    ]
    logger.info(f"Extracting audio (1 pass, 2 outputs): {video_path}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=ffmpeg_timeout_s(None))
    except subprocess.TimeoutExpired:
        result = None
    ok = (result is not None and result.returncode == 0
          and os.path.exists(asr_path) and os.path.getsize(asr_path) > 0
          and os.path.exists(hq_path) and os.path.getsize(hq_path) > 0)
    if not ok:
        for p in (asr_path, hq_path):
            if os.path.exists(p):
                os.remove(p)
        err = ("ffmpeg treo" if result is None else result.stderr[:200])
        raise RuntimeError(f"Dual audio extract failed: {err}")


def slow_segments(
    segments: list[dict],
    src_dir: str,
    dst_dir: str,
    slow_factor: float,
    max_workers: int | None = None,
) -> str:
    """Apply an atempo slow-down to every segment; returns the output directory.

    Embarrassingly parallel — hundreds of independent ffmpeg calls.
    """
    ensure_dir(dst_dir)
    # atempo chỉ nhận [0.5, 2.0] — ngoài khoảng đó ffmpeg fail từng segment
    # và video mất tiếng âm thầm. Kẹp lại và báo rõ.
    factor = min(2.0, max(0.5, slow_factor))
    if factor != slow_factor:
        logger.warning(f"VOICE_SPEED={slow_factor} ngoài khoảng "
                       f"[0.5, 2.0] của atempo — dùng {factor}")

    def _slow_one(seg: dict) -> None:
        src = seg_wav_path(src_dir, seg["id"])
        if not os.path.exists(src):
            return
        dst = os.path.join(dst_dir, os.path.basename(src))
        # Resume-safe: đầu ra còn mới hơn nguồn thì khỏi chạy lại ffmpeg —
        # chạy lại video 900 câu không tốn thêm 900 lệnh atempo vô ích.
        if (os.path.exists(dst) and os.path.getsize(dst) > 0
                and os.path.getmtime(dst) >= os.path.getmtime(src)):
            return
        try:
            with FFMPEG_SLOTS:
                result = subprocess.run(
                    ["ffmpeg", "-y", "-i", src,
                     "-filter:a", f"atempo={factor}", dst],
                    capture_output=True, text=True, timeout=_SEG_TIMEOUT_S,
                )
            failed = (result.returncode != 0 or not os.path.exists(dst)
                      or os.path.getsize(dst) == 0)
            err = result.stderr[:120] if failed else ""
        except subprocess.TimeoutExpired:
            failed, err = True, f"treo quá {_SEG_TIMEOUT_S}s"
        if failed:
            # Giữ nguyên tốc độ gốc còn hơn mất hẳn clip: các bước sau coi
            # file thiếu là "segment missing" và video bị câm đoạn đó.
            logger.error(f"atempo lỗi trên {os.path.basename(src)} — "
                         f"giữ tốc độ gốc ({err})")
            FALLBACKS.add("atempo_failed", seg["id"])
            shutil.copyfile(src, dst)

    with ThreadPoolExecutor(max_workers=max_workers or _FFMPEG_WORKERS) as pool:
        list(pool.map(_slow_one, segments))
    return dst_dir


# Fade length applied to both ends of every voice clip — long enough to kill
# clicks/pops at clip boundaries, short enough to be inaudible as a fade.
_VOICE_FADE_MS = 15


def postprocess_voice_clip(src: str, dst: str,
                           target_lufs: float = -16.0,
                           speed: float = 1.0) -> bool:
    """Broadcast-clean one TTS clip: highpass, loudness, fades.

    One ffmpeg pass per clip:
    - ``highpass 80 Hz`` — strips rumble/DC offset some TTS engines leave in
    - ``loudnorm`` (EBU R128, single pass) — every clip lands at the same
      perceived loudness regardless of voice (presets differ by several dB)
      so no line suddenly shouts or whispers
    - 15 ms fade-in/out — kills boundary clicks when clips land on the mix

    ``src``/``dst`` may differ or be equal (temp + replace). On failure the
    raw clip is kept — a rough-sounding line beats a missing one.
    """
    dur = wav_duration_s(src)
    if not dur or dur < 0.15:
        # Too short for loudnorm's analysis window (silence stubs etc.).
        if src != dst:
            shutil.copyfile(src, dst)
        return False
    # loudnorm nội bộ chạy ở 192 kHz và GIỮ mức đó ở đầu ra nếu không ép
    # lại — file phình 8 lần và mọi bước sau chậm theo. Ép về rate gốc.
    src_rate = 24000
    try:
        import wave as _wave
        with _wave.open(src, "rb") as w:
            src_rate = w.getframerate()
    except (OSError, EOFError):
        pass
    fade_s = _VOICE_FADE_MS / 1000.0
    # atempo gộp luôn vào đây: mỗi câu chỉ còn MỘT lệnh ffmpeg thay vì hai
    # (hậu kỳ rồi VOICE_SPEED). Fade phải tính trên thời lượng SAU khi đổi
    # tốc độ, nên atempo đứng trước afade.
    tempo = speed if speed > 0 else 1.0
    speed_filter = ""
    out_dur = dur
    if abs(tempo - 1.0) >= 0.005:
        tempo = min(2.0, max(0.5, tempo))
        speed_filter = f"atempo={tempo:.3f},"
        out_dur = dur / tempo
    filters = (
        f"highpass=f=80,"
        f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11,"
        f"{speed_filter}"
        f"afade=t=in:st=0:d={fade_s},"
        f"afade=t=out:st={max(0.0, out_dur - fade_s):.3f}:d={fade_s}"
    )
    tmp = dst + ".post.tmp.wav"
    try:
        with FFMPEG_SLOTS:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", src, "-filter:a", filters,
                 "-ar", str(src_rate), "-acodec", "pcm_s16le", tmp],
                capture_output=True, text=True, timeout=_SEG_TIMEOUT_S,
            )
        failed = (result.returncode != 0 or not os.path.exists(tmp)
                  or os.path.getsize(tmp) == 0)
        err = result.stderr[:120] if failed else ""
    except subprocess.TimeoutExpired:
        failed, err = True, f"treo quá {_SEG_TIMEOUT_S}s"
    if failed:
        logger.warning(f"Hậu kỳ giọng lỗi trên {os.path.basename(src)} — "
                       f"giữ clip thô ({err})")
        FALLBACKS.add("postprocess_failed", _seg_id_from_path(src))
        if os.path.exists(tmp):
            os.remove(tmp)
        if src != dst:
            shutil.copyfile(src, dst)
        return False
    os.replace(tmp, dst)
    return True


def postprocess_voice_clips(segments: list[dict], src_dir: str, dst_dir: str,
                            target_lufs: float = -16.0,
                            max_workers: int | None = None,
                            speed: float = 1.0,
                            on_done=None) -> str:
    """Post-process every segment clip into ``dst_dir`` (parallel ffmpeg).

    Skips clips whose processed output already exists and is newer than the
    source — resume-safe like every other per-segment cache.
    """
    ensure_dir(dst_dir)

    def _one(seg: dict) -> None:
        src = seg_wav_path(src_dir, seg["id"])
        if not os.path.exists(src):
            return
        dst = os.path.join(dst_dir, os.path.basename(src))
        if (os.path.exists(dst) and os.path.getsize(dst) > 0
                and os.path.getmtime(dst) >= os.path.getmtime(src)):
            return
        postprocess_voice_clip(src, dst, target_lufs, speed=speed)

    done = 0
    lock = threading.Lock()

    def _tracked(seg: dict) -> None:
        nonlocal done
        _one(seg)
        if on_done is not None:
            with lock:
                done += 1
                n = done
            on_done(n, len(segments))

    with ThreadPoolExecutor(max_workers=max_workers or _FFMPEG_WORKERS) as pool:
        list(pool.map(_tracked, segments))
    return dst_dir


def wav_duration_s(path: str) -> float | None:
    """Duration of a WAV file from its header — no audio data loaded.

    Orders of magnitude cheaper than AudioSegment.from_wav for the many
    places that only need the length (timeline fit on 900+ segments).
    Returns None when the header cannot be read (corrupt/non-PCM file).
    """
    import wave

    try:
        with wave.open(path, "rb") as w:
            rate = w.getframerate()
            return w.getnframes() / rate if rate else None
    except (wave.Error, EOFError, OSError):
        return None


def _duck_envelope(n: int, b0: int, rate: int,
                   intervals: list[tuple[float, float]],
                   duck_db: float):
    """Gain multiplier (n,) cho một block nhạc nền: 1.0 ngoài lời thoại,
    ``10^(duck_db/20)`` trong lời thoại, trượt tuyến tính ``_DUCK_RAMP_S``
    ở hai mép. Các câu sát nhau tự hoà làm một vùng duck liền mạch (lấy
    min của các envelope)."""
    import numpy as np

    env = np.ones(n, dtype=np.float32)
    duck_gain = 10.0 ** (duck_db / 20.0)
    ramp = _DUCK_RAMP_S
    t0 = b0 / rate
    t1 = (b0 + n) / rate
    for s, e in intervals:
        # Vùng ảnh hưởng của câu (gồm cả hai dốc ramp) giao với block này?
        if e + ramp <= t0 or s - ramp >= t1:
            continue
        # Thời điểm từng mẫu trong block (giây, tương đối theo track).
        i_lo = max(0, int((s - ramp - t0) * rate))
        i_hi = min(n, int((e + ramp - t0) * rate) + 1)
        idx = np.arange(i_lo, i_hi, dtype=np.float32) / rate + t0
        # Khoảng cách tới lõi câu [s, e]: 0 trong lõi, tăng dần ra mép.
        dist = np.maximum(0.0, np.maximum(s - idx, idx - e))
        frac = np.clip(1.0 - dist / ramp, 0.0, 1.0)  # 1 = duck hết cỡ
        seg_env = 1.0 + frac * (duck_gain - 1.0)
        env[i_lo:i_hi] = np.minimum(env[i_lo:i_hi], seg_env)
    return env


def _decode_resampled(path: str, rate: int, ch: int):
    """Decode một clip WAV về mảng int32 (n, ch) ở đúng rate/kênh của mix.

    Dùng ffmpeg (bộ resample swr, chất lượng cao) thay cho
    ``pydub.set_frame_rate`` (nội suy tuyến tính audioop — sinh méo/aliasing
    khi kéo 24 kHz lên 44.1 kHz). Xuất s16le thẳng ra stdout — không file
    tạm. ffmpeg lỗi thì rơi về pydub để không câm mất clip.
    """
    import numpy as np

    try:
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", path,
             "-f", "s16le", "-ar", str(rate), "-ac", str(ch), "-"],
            capture_output=True, timeout=_SEG_TIMEOUT_S,
        )
        if result.returncode == 0 and result.stdout:
            return (np.frombuffer(result.stdout, dtype=np.int16)
                    .astype(np.int32).reshape(-1, ch))
    except (subprocess.TimeoutExpired, OSError):
        pass
    logger.warning(f"ffmpeg decode lỗi trên {os.path.basename(path)} — "
                   "dùng pydub")
    seg_audio = (AudioSegment.from_wav(path)
                 .set_frame_rate(rate).set_channels(ch).set_sample_width(2))
    return np.array(seg_audio.get_array_of_samples(),
                    dtype=np.int32).reshape(-1, ch)


def _soft_limit(block):
    """Hạn biên mềm thay cho cắt cứng khi giọng + nhạc nền vượt trần int16.

    Dưới ngưỡng ~ -1 dBFS giữ nguyên từng mẫu (đa số block đi qua nguyên
    vẹn, byte-identical); phần vượt ngưỡng được nén dần bằng tanh về trần
    32767 — đỉnh to mấy cũng không gãy sóng vuông thành tiếng rè như
    ``np.clip`` thuần.
    """
    import numpy as np

    T, M = 29000.0, 32767.0
    over = (block > T) | (block < -T)
    if not over.any():
        return block
    v = block[over].astype(np.float32)
    mag = np.abs(v)
    block[over] = (np.sign(v) * (T + (M - T) * np.tanh(
        (mag - T) / (M - T)))).astype(np.int32)
    return block


def merge_segments(
    segments: list[dict],
    segment_dir: str,
    output_path: str,
    total_duration: float,
    background_path: str | None = None,
    background_gain_db: float = 0.0,
    duck_voice_db: float = 0.0,
) -> str:
    """Mix per-segment dub audio onto a background track, block by block.

    ``background_path`` may point to a clean instrumental (Demucs ``no_vocals``)
    or to the unmodified ``original_audio.wav``; in the latter case set
    ``background_gain_db`` to a negative value (e.g. -12.0 ≈ 25% volume) so the
    original speech sits under the new narration instead of competing with it.

    ``duck_voice_db`` < 0 bật sidechain-style ducking: nhạc nền tự nhỏ đi
    đúng bấy nhiêu dB trong lúc có giọng đọc (ramp 120 ms hai mép) và hồi
    lại ở khoảng lặng — giọng luôn nổi trên nhạc mà không phải hạ nền cả bài.

    Streaming design: the background is normalised once by ffmpeg (rate,
    gain, duration) into a temp WAV on disk, then mixed with the segments in
    60-second blocks written straight to the output file. Peak RAM stays at
    one block (~10 MB) regardless of video length — the previous whole-file
    numpy buffer needed ~1 GB for a 20-minute video.
    """
    import wave

    import numpy as np

    total_ms = int(total_duration * 1000)
    rate = _MIN_MERGE_RATE

    # Normalise the background on disk: target rate, gain, padded/cut to the
    # exact duration. ffmpeg streams — no RAM cost for long videos.
    bg_tmp = output_path + ".bg.tmp.wav"
    bg_wave = None
    ch = 1
    if background_path and os.path.exists(background_path):
        filters = [f"aresample={rate}",
                   f"apad=whole_dur={total_duration}",
                   f"atrim=end={total_duration}"]
        if background_gain_db:
            filters.insert(0, f"volume={background_gain_db}dB")
        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", background_path,
                 "-filter:a", ",".join(filters),
                 "-acodec", "pcm_s16le", bg_tmp],
                capture_output=True, text=True,
                timeout=ffmpeg_timeout_s(total_duration),
            )
            ok = result.returncode == 0 and os.path.getsize(bg_tmp) > 0
            err = result.stderr[:200] if not ok else ""
        except subprocess.TimeoutExpired:
            ok, err = False, "ffmpeg treo khi chuẩn hóa nhạc nền"
        if ok:
            bg_wave = wave.open(bg_tmp, "rb")
            ch = bg_wave.getnchannels()
        else:
            logger.warning(f"Background normalise failed, using silent base: "
                           f"{err}")
    elif background_path:
        logger.warning(f"Background not found: {background_path}; using silent base")

    total_frames = int(total_duration * rate)
    block_frames = _MERGE_BLOCK_S * rate

    # Sort segments by start; the block loop walks this list with a window.
    seg_index: list[tuple[float, float, dict]] = []
    for seg in segments:
        seg_file = seg_wav_path(segment_dir, seg["id"])
        if not os.path.exists(seg_file):
            logger.warning(f"Segment file not found: {seg_file}, skipping")
            continue
        dur = wav_duration_s(seg_file)
        if not dur:
            continue
        seg_index.append((float(seg["start"]), float(seg["start"]) + dur, seg))
    seg_index.sort(key=lambda x: x[0])

    # Khoảng có giọng đọc — nguồn cho envelope ducking của nhạc nền.
    duck_intervals = ([(s, e) for s, e, _ in seg_index]
                      if (duck_voice_db and duck_voice_db < 0
                          and bg_wave is not None) else [])

    out = wave.open(output_path, "wb")
    out.setnchannels(ch)
    out.setsampwidth(2)
    out.setframerate(rate)

    # Segment vắt qua N block bị decode N lần — cache mảng đã decode theo
    # id, xóa ngay khi block đã đi qua hết segment (RAM giữ tối đa vài
    # segment đang chồng lên block hiện tại). Kết quả byte-identical.
    seg_cache: dict = {}

    try:
        for b0 in range(0, total_frames, block_frames):
            b1 = min(b0 + block_frames, total_frames)
            n = b1 - b0
            if bg_wave is not None:
                raw = bg_wave.readframes(n)
                block = np.frombuffer(raw, dtype=np.int16).astype(np.int32)
                if len(block) < n * ch:   # background shorter than expected
                    block = np.concatenate(
                        [block, np.zeros(n * ch - len(block), dtype=np.int32)])
                block = block.reshape(-1, ch)
                if duck_intervals:
                    env = _duck_envelope(n, b0, rate, duck_intervals,
                                         duck_voice_db)
                    block = (block * env[:, None]).astype(np.int32)
            else:
                block = np.zeros((n, ch), dtype=np.int32)

            t0, t1 = b0 / rate, b1 / rate
            for sid in [sid for sid, (_, cached_end) in seg_cache.items()
                        if cached_end <= t0]:
                del seg_cache[sid]
            for seg_start, seg_end, seg in seg_index:
                if seg_end <= t0:
                    continue
                if seg_start >= t1:
                    break
                sid = seg["id"]
                cached = seg_cache.get(sid)
                if cached is None:
                    seg_file = seg_wav_path(segment_dir, seg["id"])
                    arr = _decode_resampled(seg_file, rate, ch)
                    seg_cache[sid] = (arr, seg_end)
                else:
                    arr = cached[0]
                start_f = int(seg_start * rate)
                gs = max(start_f, b0)
                ge = min(start_f + len(arr), b1)
                if ge <= gs:
                    continue
                block[gs - b0:ge - b0] += arr[gs - start_f:ge - start_f]

            out.writeframes(
                np.clip(_soft_limit(block), -32768, 32767)
                .astype(np.int16).tobytes())
    finally:
        out.close()
        if bg_wave is not None:
            bg_wave.close()
        if os.path.exists(bg_tmp):
            os.remove(bg_tmp)

    if bg_wave is not None:
        gain_note = f" (gain {background_gain_db:+.1f} dB)" if background_gain_db else ""
        bg_label = f"with BGM{gain_note}"
    else:
        bg_label = "silent base"
    logger.info(
        f"Audio merged ({bg_label}): {output_path} "
        f"({len(seg_index)} segments, {total_duration:.1f}s)"
    )
    return output_path
