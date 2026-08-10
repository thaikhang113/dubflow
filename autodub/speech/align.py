"""Forced alignment cho phụ đề karaoke — mốc THẬT của từng chữ tiếng Việt.

CapCut lấy mốc chữ bằng cách chạy ASR trên audio. Ở đây điều kiện còn tốt
hơn: audio là giọng TTS studio-sạch (không nhạc nền) và VĂN BẢN ĐÃ BIẾT
TRƯỚC (chính là bản dịch) — chỉ cần mốc thời gian, không cần đoán chữ.

Cách làm: Whisper ``base`` (đã có sẵn qua faster-whisper trong app, ~150 MB,
tự tải lần đầu) nghe TỪNG clip WAV với ``word_timestamps=True``, rồi khớp
chuỗi chữ Whisper nghe được với chuỗi chữ của bản dịch:

- Số chữ hai bên bằng nhau (đa số — tiếng Việt đơn âm tiết) → map 1:1.
- Lệch nhau → nội suy vị trí (chữ thứ i của bản dịch lấy mốc của chữ
  ``i * n_asr / n_text`` phía Whisper). Nhịp vẫn đúng vì tổng thời lượng và
  các mốc neo là thật; chỉ ranh giới giữa các chữ bị nhòe nhẹ.

Mỗi clip độc lập — một clip khớp hỏng chỉ mất alignment của đúng clip đó
(caller tự rơi về ước lượng). Kết quả cache JSON trong work_dir nên resume
và rebuild không phải nghe lại.
"""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor

from autodub.utils import save_json_atomic, seg_wav_path, setup_logging

logger = setup_logging("autodub.align")

# Model alignment: "base" đủ cho audio TTS sạch; đổi chỉ khi có lý do đo được.
ALIGN_MODEL = "base"

# Clip ngắn hơn mức này không đáng chạy model — ước lượng là đủ.
_MIN_CLIP_S = 0.4


def _align_workers() -> int:
    """Số clip nghe song song. Base model nhỏ nên nghẽn là CPU, không phải RAM."""
    return max(1, min(4, (os.cpu_count() or 4) // 2))


def _load_align_model():
    """Whisper base cho alignment. Trả ``(model, device, n_workers)``.

    ``num_workers`` cho phép gọi ``transcribe`` từ nhiều luồng Python cùng lúc
    (ctranslate2 giữ một bản trọng số, mỗi luồng một bộ đệm) — canh phụ đề là
    hàng trăm clip ngắn độc lập nên đây là chỗ song song hóa gần như tuyến tính.
    """
    from faster_whisper import WhisperModel

    from autodub.resources import GPU_LOCK, cpu_share
    from autodub.speech.transcriber import _enable_cuda_dlls
    if _enable_cuda_dlls():
        with GPU_LOCK:
            # float16 là đường nhanh nhất của ctranslate2 trên GPU; int8 trên
            # CUDA phải giải lượng tử liên tục nên chậm hơn.
            for compute in ("float16", "int8_float16", "int8"):
                try:
                    model = WhisperModel(ALIGN_MODEL, device="cuda",
                                         compute_type=compute)
                    # GPU đã bị một model chiếm hết — thêm luồng chỉ tranh nhau.
                    return model, "cuda", 1
                except Exception as e:
                    logger.debug(f"Alignment GPU {compute} không chạy ({e})")
        logger.info("Alignment dùng CPU")
    workers = _align_workers()
    model = WhisperModel(ALIGN_MODEL, device="cpu", compute_type="int8",
                         cpu_threads=cpu_share(workers), num_workers=workers)
    return model, "cpu", workers


def _asr_words(model, wav_path: str) -> list[tuple[str, float, float]]:
    """Chữ + mốc (tương đối trong clip) Whisper nghe được từ một clip."""
    segments, _info = model.transcribe(
        wav_path, language="vi", word_timestamps=True,
        beam_size=1,              # audio sạch — greedy đủ, nhanh gấp đôi
        condition_on_previous_text=False,
        vad_filter=False,         # clip đã là lời nói thuần
    )
    out: list[tuple[str, float, float]] = []
    for seg in segments:
        for w in seg.words or []:
            token = w.word.strip()
            if token:
                out.append((token, float(w.start), float(w.end)))
    return out


def _map_words(
    text_words: list[str],
    asr_words: list[tuple[str, float, float]],
    clip_start: float,
    clip_dur: float,
) -> list[tuple[str, float, float]] | None:
    """Gán mốc cho từng chữ của bản dịch từ mốc Whisper nghe được.

    Trả về mốc TUYỆT ĐỐI (đã cộng ``clip_start``), hoặc None khi kết quả
    ASR quá lệch để tin (quá ít chữ so với văn bản).
    """
    nt, na = len(text_words), len(asr_words)
    if nt == 0 or na == 0:
        return None
    # ASR nghe ra quá ít chữ (nuốt nửa câu) → mốc nội suy sẽ sai nhịp nặng;
    # thà ước lượng đều còn hơn.
    if na < nt * 0.5:
        return None

    out: list[tuple[str, float, float]] = []
    if na == nt:
        pairs = zip(text_words, asr_words)
        for token, (_w, t0, t1) in pairs:
            out.append((token, clip_start + t0, clip_start + t1))
    else:
        # Nội suy vị trí: chữ i của văn bản ↔ vùng i*na/nt của ASR.
        for i, token in enumerate(text_words):
            j0 = min(na - 1, int(i * na / nt))
            j1 = min(na - 1, int((i + 1) * na / nt))
            t0 = asr_words[j0][1]
            t1 = asr_words[j1][2] if j1 > j0 else asr_words[j0][2]
            out.append((token, clip_start + t0, clip_start + max(t1, t0)))

    # Vá đơn điệu: mốc phải không lùi và nằm trong clip (ASR đôi khi trả
    # end < start quanh khoảng lặng).
    hi = clip_start + clip_dur
    prev = clip_start
    fixed: list[tuple[str, float, float]] = []
    for token, t0, t1 in out:
        t0 = min(max(t0, prev), hi)
        t1 = min(max(t1, t0 + 0.02), hi)
        fixed.append((token, round(t0, 3), round(t1, 3)))
        prev = t0
    return fixed


def align_segments(
    segments: list[dict],
    merge_dir: str,
    text_field: str,
    cache_path: str | None = None,
) -> dict[int, list[tuple[str, float, float]]]:
    """Alignment thật cho mọi segment. Trả ``{id: [(chữ, t0, t1), ...]}``.

    Mốc trả về TUYỆT ĐỐI theo timeline video (clip đặt tại ``seg["start"]``).
    Segment thiếu file/khớp hỏng thì vắng mặt trong kết quả — caller bù bằng
    ước lượng. Cache theo (mtime clip, text) nên chỉ câu bị re-TTS/sửa chữ
    mới phải nghe lại.
    """
    from autodub.media.audio import wav_duration_s

    cache: dict = {}
    if cache_path and os.path.exists(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as f:
                cache = json.load(f)
        except (json.JSONDecodeError, OSError):
            cache = {}

    out: dict[int, list[tuple[str, float, float]]] = {}
    todo: list[tuple[dict, str, float, str]] = []  # (seg, wav, dur, key)
    for seg in segments:
        sid = seg.get("id")
        text = str(seg.get(text_field, "")).strip()
        if not text:
            continue
        wav = seg_wav_path(merge_dir, sid)
        if not os.path.exists(wav):
            continue
        dur = wav_duration_s(wav)
        if not dur or dur < _MIN_CLIP_S:
            continue
        key = f"{sid}:{int(os.path.getmtime(wav))}:{hash(text) & 0xFFFFFFFF}"
        hit = cache.get(key)
        if hit:
            # Cache giữ mốc TƯƠNG ĐỐI trong clip — cộng start hiện tại để
            # timeline mềm dịch clip đi đâu mốc vẫn theo đó.
            base = float(seg["start"])
            out[sid] = [(w, round(base + t0, 3), round(base + t1, 3))
                        for w, t0, t1 in hit]
            continue
        todo.append((seg, wav, dur, key))

    if not todo:
        return out

    n_cached = len(out)
    logger.info(f"Đang canh phụ đề nhảy đúng nhịp giọng đọc "
                f"({len(todo)} câu"
                + (f", {n_cached} câu dùng lại của lần trước" if n_cached else "")
                + ") — chờ chút...")
    try:
        model, _device, n_workers = _load_align_model()
    except Exception as e:
        logger.warning(f"Không canh được phụ đề theo giọng đọc ({e}) — "
                       "chữ sẽ chia đều theo thời lượng câu")
        return out

    def _one(item):
        seg, wav, dur, key = item
        sid = seg.get("id")
        text_words = str(seg.get(text_field, "")).split()
        try:
            asr = _asr_words(model, wav)
        except Exception as e:
            logger.debug(f"ASR alignment câu {sid} lỗi ({e}) — ước lượng")
            return None
        mapped = _map_words(text_words, asr, float(seg["start"]), dur)
        if mapped is None:
            return None
        return sid, key, float(seg["start"]), mapped

    if n_workers > 1:
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            done = list(pool.map(_one, todo))
    else:
        done = [_one(item) for item in todo]

    new_cache_entries: dict = {}
    n_ok = 0
    for res in done:
        if res is None:
            continue
        sid, key, base, mapped = res
        out[sid] = mapped
        n_ok += 1
        new_cache_entries[key] = [
            [w, round(t0 - base, 3), round(t1 - base, 3)]
            for w, t0, t1 in mapped
        ]

    # Model base nhỏ; thả tham chiếu là đủ (ctranslate2 tự nhả khi GC).
    del model

    n_est = len(todo) - n_ok
    logger.info(f"Canh phụ đề xong: {n_ok}/{len(todo)} câu khớp chính xác "
                "theo giọng đọc"
                + (f", {n_est} câu chia đều theo thời lượng" if n_est else ""))
    if cache_path and new_cache_entries:
        try:
            save_json_atomic({**cache, **new_cache_entries}, cache_path)
        except OSError:
            pass
    return out
