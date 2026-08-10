import ctypes
import json
import os
import subprocess
import threading
from collections import deque

from autodub.config import Settings
from autodub.languages import WHISPER_LANG_MAP
from autodub.resources import GPU_LOCK
from autodub.utils import bundled_file, gpu_venv_dir, save_json_atomic, setup_logging

logger = setup_logging("autodub.transcriber")

_WHISPER_WORKER_SCRIPT = bundled_file("autodub", "speech", "asr_whisper_worker.py")


def _enable_cuda_dlls() -> bool:
    """Cho faster-whisper nạp được cuBLAS/cuDNN trên Windows.

    ctranslate2 cần cublas và cudnn, mà venv chính không mang theo — nhưng
    bản torch trong venv CUDA thì có sẵn. Nạp trước từ đó là Whisper chạy
    được trên card đồ họa mà không phải cài thêm gì. Trả về True khi các
    tệp .dll dùng được (ngoài Windows thì coi như hệ thống đã có).
    """
    if os.name != "nt":
        return True
    import glob

    venv = gpu_venv_dir()
    if not venv:
        return False
    lib_dir = os.path.join(venv, "Lib", "site-packages", "torch", "lib")
    # Glob thay vì ghim cublas64_12: torch cu13 mang cublas64_13 — ghim
    # cứng số phiên bản là rơi về CPU âm thầm sau một lần nâng cấp venv.
    matches = glob.glob(os.path.join(lib_dir, "cublas64_*.dll"))
    if not matches:
        return False
    try:
        os.add_dll_directory(lib_dir)
        ctypes.CDLL(matches[0])
        return True
    except OSError:
        return False


def asr_will_use_gpu(settings: Settings, language: str) -> bool:
    """Bước ASR sắp tới có tranh card đồ họa với Demucs không?

    Trả về False khi ASR chắc chắn chạy CPU: Paraformer (ONNX/CPU trong
    .venv-asr) cho tiếng Trung, hoặc Whisper mà không nạp được cuBLAS/cuDNN.
    Pipeline dùng câu trả lời này để quyết định có cho Demucs (GPU) chạy
    song song với ASR hay không — sai về phía True là an toàn (chỉ mất cơ
    hội song song, không bao giờ làm hai việc giành nhau GPU).
    """
    if (settings.asr_engine == "paraformer"
            and (language or "").lower().startswith("zh")
            and settings.paraformer_configured()):
        return False
    return _enable_cuda_dlls()


def _load_whisper_model(model_name: str, settings: Settings):
    """Load faster-whisper on GPU when possible, falling back to CPU.

    ``model_name`` may be "auto": large-v3 when CUDA works (ASR runs
    GPU-exclusive so the ~3 GB fits even on 6 GB cards), medium on CPU —
    the accuracy gap on Chinese sources is the single biggest translation-
    quality lever upstream of the translator itself.

    Returns ``(model, device)`` — device is "cuda" or "cpu"; the batch
    cache needs it to decide whether keeping the model resident is safe.
    """
    from faster_whisper import WhisperModel

    if _enable_cuda_dlls():
        resolved = settings.resolved_whisper_model(cuda_available=True)
        # GPU_LOCK chỉ quanh lúc NẠP: đây là đoạn xin VRAM, cũng là chỗ chen
        # với Demucs thì OOM. Giữ lock suốt lượt nghe sẽ chặn Demucs hàng chục
        # phút mà không cần thiết. Xem autodub/resources.py.
        with GPU_LOCK:
            # float16 là kiểu tính GPU chạy nhanh nhất của ctranslate2 (Tensor
            # Core). int8 trên CUDA phải giải lượng tử liên tục nên CHẬM hơn
            # float16 dù ít VRAM hơn — chỉ dùng khi float16 không nạp được.
            for compute in ("float16", "int8_float16", "int8"):
                try:
                    model = WhisperModel(resolved, device="cuda",
                                         compute_type=compute)
                    logger.info(f"Whisper '{resolved}' chạy trên GPU "
                                f"(CUDA, {compute})")
                    return model, "cuda"
                except Exception as e:
                    logger.warning(
                        f"Whisper GPU {compute} không chạy được ({e})")
        logger.warning("Không chạy được Whisper trên GPU — dùng CPU")
    resolved = settings.resolved_whisper_model(cuda_available=False)
    return WhisperModel(resolved, device="cpu", compute_type="int8"), "cpu"


def _gpu_total_vram_gb() -> float:
    """Tổng VRAM (GB) của card lớn nhất; 0.0 nếu không đọc được."""
    import subprocess

    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if out.returncode == 0 and out.stdout.strip():
            return max(float(x) for x in out.stdout.split()) / 1024.0
    except Exception:
        pass
    return 0.0


class WhisperCache:
    """Dùng lại một model Whisper đã nạp xuyên suốt nhiều video (batch).

    Nạp large-v3 từ đĩa mất hàng chục giây mỗi video — với lô hàng trăm
    video là hàng giờ vô ích. Giữ thường trú thì phải cân VRAM: trên CPU
    luôn an toàn; trên GPU chỉ giữ khi card ≥ 10 GB (card 6 GB cần trả
    ~2 GB của Whisper cho Demucs của video kế tiếp — giữ lại sẽ đẩy
    Demucs rơi về CPU, chậm hơn nhiều so với 20 giây tiết kiệm được).
    """

    _KEEP_GPU_MIN_VRAM_GB = 10.0

    def __init__(self):
        self._model = None
        self._key = None

    def get(self, settings: Settings):
        """Trả về model đã nạp; tự quyết định có giữ thường trú hay không."""
        key = settings.whisper_model
        if self._model is not None and self._key == key:
            logger.info("Dùng lại model Whisper đã nạp (batch)")
            return self._model
        self.close()
        model, device = _load_whisper_model(key, settings)
        if device == "cpu" or _gpu_total_vram_gb() >= self._KEEP_GPU_MIN_VRAM_GB:
            self._model = model
            self._key = key
        return model

    def owns(self, model) -> bool:
        return model is not None and model is self._model

    def close(self) -> None:
        if self._model is not None:
            self._model = None
            self._key = None
            _release_vram()


def transcribe(audio_path: str, language: str, settings: Settings,
               whisper_cache: "WhisperCache | None" = None) -> list[dict]:
    """Transcribe audio with the configured local ASR (free, offline).

    Engines: Whisper (default, multilingual) or Paraformer (Chinese only,
    CPU/ONNX in .venv-asr — more accurate on zh sources). Paraformer failures
    or misconfiguration fall back to Whisper so a run never dies here.

    Segments keep the engine's fragment granularity — translation, subtitles,
    the editor AND the voice all follow the source video's own per-fragment
    timeline (strict 1:1 rendering, one clip per segment).
    """
    segments = None
    if settings.asr_engine == "paraformer":
        if not (language or "").lower().startswith("zh"):
            logger.warning("Paraformer chỉ hỗ trợ tiếng Trung — dùng Whisper "
                           f"cho ngôn ngữ '{language}'")
        elif not settings.paraformer_configured():
            logger.warning("Paraformer chưa cài (đúp chuột 'Cai dat ASR tieng "
                           "Trung (Paraformer).bat') — dùng Whisper")
        else:
            try:
                from autodub.speech.paraformer_transcriber import (
                    transcribe_paraformer)
                segments = transcribe_paraformer(audio_path, settings)
            except Exception as e:
                logger.warning(f"Paraformer lỗi ({e}) — chuyển sang Whisper")
    if segments is None:
        # Ưu tiên subprocess worker (venv riêng) để không cần bundle
        # faster-whisper trong exe — cắt ~112 MB kích thước bản phân phối.
        # Fallback về in-process khi venv chưa cài (dev) hoặc cache đang giữ.
        if whisper_cache is None and settings.whisper_venv_configured():
            try:
                segments = _transcribe_whisper_subprocess(
                    audio_path, language, settings)
            except Exception as e:
                logger.warning(
                    f"Whisper subprocess lỗi ({e}) — thử in-process")
                segments = None
        if segments is None:
            segments = _transcribe_whisper(audio_path, language, settings,
                                           whisper_cache)

    logger.info(f"Transcription complete: {len(segments)} raw segments")

    # Split long segments into ~MAX_SEGMENT_DURATION chunks
    segments = split_long_segments(segments, max_duration=10.0)
    logger.info(f"After splitting: {len(segments)} segments")

    # words đã phục vụ xong việc cắt — bỏ khỏi transcript trên đĩa (giữ
    # format cũ, file nhỏ, các bước sau không phải biết tới nó).
    for seg in segments:
        seg.pop("words", None)

    return segments


def _transcribe_whisper_subprocess(
    audio_path: str, language: str, settings: Settings
) -> list[dict]:
    """Chạy Whisper trong .venv-whisper (subprocess) — không cần bundle
    faster-whisper/ctranslate2 trong exe, giảm ~112 MB bản phân phối.

    Dùng cùng JSON-line protocol với asr_paraformer_worker nên kết quả
    có format Whisper-shaped giống hệt đường in-process.
    """
    # Tìm thư mục torch/lib để worker có thể nạp cuBLAS trên Windows
    cuda_dll_dir = ""
    venv = gpu_venv_dir()
    if venv and os.name == "nt":
        _lib = os.path.join(venv, "Lib", "site-packages", "torch", "lib")
        if os.path.isdir(_lib):
            cuda_dll_dir = _lib

    cmd = [
        settings.whisper_venv_python_path(),
        _WHISPER_WORKER_SCRIPT,
        "--audio",     audio_path,
        "--model",     settings.whisper_model,
        "--language",  language or "",
        "--beam-size", str(settings.whisper_beam_size),
        "--model-dir", settings.whisper_model_dir_path(),
    ]
    if cuda_dll_dir:
        cmd += ["--cuda-dll-dir", cuda_dll_dir]

    logger.info("Khởi động Whisper worker (subprocess) ...")
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )

    stderr_tail: deque[str] = deque(maxlen=30)

    def _drain() -> None:
        try:
            for line in proc.stderr:
                line = line.rstrip()
                if line:
                    stderr_tail.append(line)
                    logger.debug(f"[whisper-worker] {line}")
        except (ValueError, OSError):
            pass

    threading.Thread(target=_drain, daemon=True).start()

    # Đọc {"ready": true} trước khi gửi request
    ready_line = proc.stdout.readline().strip()
    try:
        ready = json.loads(ready_line)
    except (json.JSONDecodeError, ValueError):
        proc.kill()
        raise RuntimeError(
            f"Whisper worker không phản hồi ready: {ready_line!r}\n"
            + "\n".join(stderr_tail))
    if not ready.get("ready"):
        proc.kill()
        raise RuntimeError(
            f"Whisper worker báo lỗi: {ready}\n" + "\n".join(stderr_tail))

    logger.info("Whisper worker sẵn sàng — gửi request nhận dạng")

    # Gửi request
    req = {"audio": audio_path, "language": language or "",
           "beam_size": settings.whisper_beam_size}
    proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
    proc.stdin.flush()
    proc.stdin.close()

    segments: list[dict] = []
    done = False
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("error"):
                raise RuntimeError(f"Whisper worker: {msg['error']}")
            if msg.get("seg"):
                start = float(msg["start"])
                end   = float(msg["end"])
                seg: dict = {
                    "id":       msg.get("id", len(segments) + 1),
                    "text":     str(msg.get("text", "")).strip(),
                    "start":    round(start, 3),
                    "end":      round(end, 3),
                    "duration": round(end - start, 3),
                }
                words = msg.get("words")
                if words:
                    seg["words"] = words
                segments.append(seg)
                logger.info(f"Segment {seg['id']}: "
                            f"[{start:.1f}s-{end:.1f}s] "
                            f"{seg['text'][:50]}...")
            elif msg.get("done"):
                done = True
                lang = msg.get("language", "")
                if lang:
                    logger.info(
                        f"Ngôn ngữ: {lang} "
                        f"({msg.get('language_prob', 0):.0%})")
        proc.wait(timeout=7200)
    finally:
        if proc.poll() is None:
            proc.kill()
        for s in (proc.stdout, proc.stderr):
            if s:
                try:
                    s.close()
                except Exception:
                    pass

    tail = "\n".join(stderr_tail)
    if not done:
        raise RuntimeError(
            f"Whisper worker thoát bất thường (exit {proc.returncode})"
            + (f"\n{tail}" if tail else ""))
    if not segments:
        raise RuntimeError(
            "Whisper worker không nhận dạng được câu nào"
            + (f"\n{tail}" if tail else ""))
    return segments


def _release_vram() -> None:
    """Free the Whisper model's VRAM immediately after transcription.

    Whisper large-v3 giữ khoảng 2 GB VRAM; để nó nằm lại tới hết lượt chạy
    là chiếm chỗ vô ích của các bước sau. ctranslate2 chỉ trả bộ nhớ card khi
    đối tượng model bị thu gom — lớp gọi bỏ tham chiếu trước, rồi hàm này ép
    thu gom ngay thay vì đợi tới lúc tiến trình thoát.
    """
    import gc

    gc.collect()
    logger.info("Đã giải phóng bộ nhớ Whisper cho bước tạo giọng")


def _transcribe_whisper(audio_path: str, language: str, settings: Settings,
                        whisper_cache: "WhisperCache | None" = None) -> list[dict]:
    """Local ASR via faster-whisper — free, offline, no API key needed.

    ``word_timestamps=True``: mỗi segment mang kèm mảng ``words``
    (word + start/end thật) để :func:`split_long_segments` cắt câu dài tại
    mốc thời gian THẬT của từ, thay vì chia theo tỷ lệ ký tự (đoán). Mảng
    words bị loại khỏi kết quả cuối — transcript trên đĩa giữ format cũ.
    """
    whisper_lang = WHISPER_LANG_MAP.get(language, language.split("-")[0])
    model_name = settings.whisper_model

    if whisper_cache is not None:
        model = whisper_cache.get(settings)
    else:
        logger.info(f"Loading Whisper model: {model_name} (first run downloads the model)")
        model, _device = _load_whisper_model(model_name, settings)

    logger.info(f"Starting transcription: {audio_path} (language: {whisper_lang})")
    raw_segments, info = model.transcribe(
        audio_path,
        language=whisper_lang,
        beam_size=settings.whisper_beam_size,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        word_timestamps=True,
    )
    if whisper_lang is None and getattr(info, "language", None):
        logger.info(f"Ngôn ngữ tự nhận dạng: {info.language} "
                    f"(độ tin cậy {getattr(info, 'language_probability', 0):.0%})")

    segments = []
    segment_id = 0
    for seg in raw_segments:
        text = seg.text.strip()
        if not text:
            continue
        segment_id += 1
        start = seg.start
        end = seg.end
        segment = {
            "id": segment_id,
            "text": text,
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(end - start, 3),
        }
        words = getattr(seg, "words", None)
        if words:
            segment["words"] = [
                {"word": w.word, "start": round(w.start, 3),
                 "end": round(w.end, 3)}
                for w in words
            ]
        segments.append(segment)
        logger.info(f"Segment {segment_id}: [{start:.1f}s-{end:.1f}s] {text[:50]}...")

    # The transcript is fully materialised — hand the VRAM back before the
    # TTS step sizes its worker pool. raw_segments (a generator) also pins
    # the model, so drop both before collecting. Model thường trú của
    # WhisperCache thì giữ lại (cache đã cân VRAM khi quyết định giữ).
    keep = whisper_cache is not None and whisper_cache.owns(model)
    del model, raw_segments
    if not keep:
        _release_vram()

    return segments


def _word_boundary_time(seg: dict, char_pos: int, fallback: float) -> float:
    """Thời điểm THẬT (giây) của ranh giới sau ``char_pos`` ký tự văn bản.

    Dò trong ``seg["words"]`` (word_timestamps của faster-whisper): cộng dồn
    độ dài từng từ đến khi đạt ``char_pos`` rồi lấy ``end`` của từ đó. Không
    có words (Paraformer, transcript cũ) → trả ``fallback`` (ước theo ký tự).
    """
    words = seg.get("words")
    if not words:
        return fallback
    acc = 0
    for w in words:
        acc += len(str(w.get("word", "")))
        if acc >= char_pos:
            end = w.get("end")
            return float(end) if end is not None else fallback
    return fallback


def split_long_segments(segments: list[dict], max_duration: float = 10.0) -> list[dict]:
    """Split segments longer than max_duration into smaller ones at sentence boundaries.

    Uses punctuation (. ! ? ;) to find split points. Chunk boundary TIMES come
    from real word timestamps when the ASR provided them (Whisper
    ``word_timestamps=True``) — the char-proportional estimate is only the
    fallback. A boundary that lands hundreds of ms off pushes every dub clip
    of the tail chunk onto the wrong spot, which the viewer hears as
    lip-sync drift.
    """
    import re
    result = []
    new_id = 0

    for seg in segments:
        if seg["duration"] <= max_duration:
            new_id += 1
            result.append({**seg, "id": new_id})
            continue

        # Split text at sentence boundaries. CJK marks (。！？；) carry no
        # trailing space, so match with \s* — benefits both Paraformer output
        # and Whisper zh transcripts.
        sentences = re.split(r'(?<=[.!?;。！？；])\s*', seg["text"].strip())
        sentences = [s for s in sentences if s]
        if len(sentences) <= 1:
            # No sentence boundary found, keep as-is
            new_id += 1
            result.append({**seg, "id": new_id})
            continue

        # Group sentences into chunks that fit within max_duration
        total_chars = sum(len(s) for s in sentences)
        total_duration = seg["duration"]
        start = seg["start"]

        chunk_sentences = []
        chunk_chars = 0
        consumed_chars = 0   # ký tự đã chốt vào các chunk trước (tra words)

        for sentence in sentences:
            estimated_chunk_duration = (chunk_chars + len(sentence)) / total_chars * total_duration

            # If adding this sentence exceeds max_duration and we already have content, flush
            if chunk_sentences and estimated_chunk_duration > max_duration:
                chunk_duration = chunk_chars / total_chars * total_duration
                est_end = start + chunk_duration
                consumed_chars += chunk_chars
                # Mốc thật từ word timestamps; kẹp trong (start, seg.end) để
                # words lệch/thiếu không sinh đoạn âm.
                end = _word_boundary_time(seg, consumed_chars, est_end)
                end = round(min(max(end, start + 0.1), seg["end"] - 0.1), 3)
                new_id += 1
                result.append({
                    "id": new_id,
                    "text": " ".join(chunk_sentences),
                    "start": round(start, 3),
                    "end": end,
                    "duration": round(end - start, 3),
                })
                start = end
                chunk_sentences = []
                chunk_chars = 0

            chunk_sentences.append(sentence)
            chunk_chars += len(sentence)

        # Flush remaining
        if chunk_sentences:
            # Ước lượng ký tự có thể trôi qua seg["end"] (join spaces không
            # được đếm trong total_chars) — kẹp lại để không sinh đoạn có
            # thời lượng âm.
            end = seg["end"]
            start = min(start, end - 0.1)
            new_id += 1
            result.append({
                "id": new_id,
                "text": " ".join(chunk_sentences),
                "start": round(start, 3),
                "end": round(end, 3),
                "duration": round(end - start, 3),
            })

    return result


def save_transcript(segments: list[dict], output_path: str) -> str:
    # Atomic: crash giữa chừng không được phá transcript cũ (đắt để tạo lại).
    save_json_atomic(segments, output_path)
    logger.info(f"Transcript saved: {output_path}")
    return output_path
