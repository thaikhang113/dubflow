"""Dịch qua máy chủ VoxDub — nơi dịch DUY NHẤT của ứng dụng.

Thay cho các module gọi thẳng OpenRouter/Gemini/OpenAI trước đây. Việc chia
lô, chạy song song và ghi sổ tạm vẫn nằm ở đây (máy khách biết mình có bao
nhiêu câu và cái nào đã xong); còn việc chọn mô hình, dựng lời nhắc và đọc
kết quả đã chuyển hẳn lên máy chủ.

Hai điều đáng chú ý so với bản cũ:

- Mỗi lô có ``job_id`` ổn định, sinh từ mã của lượt dịch cộng số thứ tự lô.
  Rớt mạng rồi chạy lại thì lô đó gửi đúng ``job_id`` cũ, máy chủ trả kết quả
  đã tính phí chứ không trừ credit lần nữa.
- Hết Vox (:class:`InsufficientCreditError`) DỪNG cả lượt ngay lập tức thay
  vì thử tiếp các lô còn lại — thử tiếp chỉ tạo thêm request chắc chắn hỏng.
- Lỗi TẠM THỜI (mất mạng, timeout, 429, 5xx) được gửi lại tối đa 3 lần với
  giãn cách tăng dần. Nhờ ``job_id`` idempotency, gửi lại không tốn thêm Vox —
  nên đây là cách đúng để một cú chớp mạng không giết cả lượt chạy.
"""
from __future__ import annotations

import hashlib
import random
import threading
import time
from collections import deque

from autodub.languages import TargetLang
from autodub.progress import ProgressReporter
from autodub.saas_client import (
    DeviceBlockedError,
    InsufficientCreditError,
    MaintenanceError,
    OfflineError,
    SaasError,
    get_client,
)
from autodub.text.translate_common import HOLD, TranslateCheckpoint, TranslateError
from autodub.utils import setup_logging

logger = setup_logging("autodub.translate_saas")

#: Trần lượt gọi song song. Máy chủ giới hạn 40 request/phút cho một thiết
#: bị; 4 luồng với lô 40 câu là dưới ngưỡng đó kể cả với video dài.
_WORKERS_CAP = 4

#: Số lượt gửi tối đa cho một lô (1 lần đầu + 3 lần thử lại).
_MAX_ATTEMPTS = 4
#: Giãn cách giữa các lượt thử lại, giây. Nhân thêm jitter ±20% khi dùng.
_BACKOFF_S = (2.0, 6.0, 15.0)
#: Trần nhịp gửi phía máy khách. Máy chủ cho 40 req/phút mỗi thiết bị; giữ 30
#: để còn chỗ cho lượt phân tích và rà soát chạy chung một lượt dịch.
_RATE_LIMIT = 30
_RATE_WINDOW_S = 60.0


class _RateLimiter:
    """Chặn nhịp gửi cho CẢ tiến trình, không phải cho từng luồng.

    Trần 40 req/phút là trần của THIẾT BỊ. Bốn luồng dịch mỗi luồng tự đếm thì
    tổng vẫn vượt — nên bộ đếm này dùng chung, cấp module. Giữ mốc thời gian
    của các lượt gửi trong cửa sổ một phút; đầy thì luồng gọi ngủ tới khi mốc
    cũ nhất rời cửa sổ.
    """

    def __init__(self, limit: int = _RATE_LIMIT, window_s: float = _RATE_WINDOW_S):
        self.limit = limit
        self.window_s = window_s
        self._hits: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self, sleep=time.sleep, now=time.monotonic) -> None:
        while True:
            with self._lock:
                current = now()
                while self._hits and current - self._hits[0] >= self.window_s:
                    self._hits.popleft()
                if len(self._hits) < self.limit:
                    self._hits.append(current)
                    return
                wait_s = self.window_s - (current - self._hits[0])
            sleep(max(0.01, wait_s))


#: Bộ chặn nhịp dùng chung cho mọi lượt gọi AI của tiến trình.
RATE_LIMITER = _RateLimiter()


def _is_retryable(exc: BaseException) -> bool:
    """Lỗi tạm thời — gửi lại có cơ hội thành công.

    Hết Vox, thiết bị bị khóa, bảo trì và 4xx khác đều là lỗi cố định: gửi lại
    chỉ tốn thời gian và chắc chắn nhận đúng câu trả lời đó.
    """
    if isinstance(exc, (InsufficientCreditError, DeviceBlockedError,
                        MaintenanceError)):
        return False
    if isinstance(exc, OfflineError):
        return True   # mất mạng, timeout kết nối/đọc
    if isinstance(exc, SaasError):
        return exc.code == "RATE_LIMITED" or exc.status >= 500
    return False


def _sleep_cancellable(delay_s: float, reporter: ProgressReporter | None,
                       stop: threading.Event) -> None:
    """Chờ ``delay_s`` nhưng vẫn nghe lệnh hủy (cắt lát 0.5 giây).

    ``time.sleep(15)`` làm người dùng bấm Hủy phải đợi hết 15 giây mới thấy
    app phản hồi.
    """
    deadline = time.monotonic() + delay_s
    while True:
        if reporter is not None:
            reporter.check_cancelled()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        if stop.wait(min(0.5, remaining)):
            return   # lô khác đã hết Vox — khỏi chờ nữa


def _batch_job_id(run_id: str, batch: list[dict]) -> str:
    """Khóa idempotency của một lô — ổn định giữa các lần chạy lại.

    Băm theo NỘI DUNG lô (id + text từng câu) chứ không theo số thứ tự:
    người dùng đổi ``translate_batch_size`` giữa hai lần chạy thì ranh giới
    lô xê dịch — job_id theo chỉ số sẽ trỏ vào kết quả cache của một lô KHÁC
    và ghép sai câu. Băm nội dung thì cùng lô → cùng khóa, khác lô → khác
    khóa, bất kể chỉ số.
    """
    h = hashlib.sha256()
    for seg in batch:
        h.update(f"{seg.get('id')}\x1f{seg.get('text', '')}\x1e".encode())
    return f"{run_id}-b{h.hexdigest()[:16]}"


def run_id_for(segments: list[dict], target: TargetLang) -> str:
    """Mã của một lượt dịch, tính từ chính nội dung cần dịch.

    Chạy lại cùng một transcript sinh ra cùng mã, nên các lô đã tính phí ở
    lượt trước được máy chủ nhận ra và trả về miễn phí. Sửa transcript (nghe
    lại, sửa tay) đổi mã — đúng, vì đó là nội dung khác.
    """
    h = hashlib.sha256()
    h.update(target.text_field.encode())
    for seg in segments:
        h.update(f"{seg.get('id')}\x1f{seg.get('text', '')}\x1e".encode())
    return h.hexdigest()[:24]


def _payload_segment(seg: dict, cps: float) -> dict:
    """Các trường gửi lên máy chủ cho một câu — không thừa một byte nào.

    ``start``/``end`` không giúp gì cho việc dịch (máy chủ chỉ cần biết câu
    dài bao nhiêu giây) mà nhân với hàng nghìn câu là hàng chục nghìn token
    vô ích mỗi video.
    """
    out = {"id": int(seg["id"]), "text": str(seg.get("text", ""))}
    duration = float(seg.get("duration", 0) or 0)
    if duration > 0:
        out["duration"] = round(duration, 3)
    window = float(seg.get("slot") or duration or 0)
    if window > 0:
        out["max_chars"] = max(12, int(window * cps))
    return out


def _context_from_settings(settings) -> dict:
    """Ngữ cảnh người dùng điền trong Cài đặt, đóng gói cho máy chủ."""
    if settings is None:
        return {}
    fields = {
        "videoTitle": "translate_video_title",
        "domain": "translate_domain",
        "context": "translate_context",
        "pronouns": "translate_pronouns",
        "glossary": "translate_glossary",
        "styleNotes": "translate_style_notes",
    }
    out = {}
    for key, attr in fields.items():
        value = str(getattr(settings, attr, "") or "").strip()
        if value:
            out[key] = value
    return out


def _prev_context(all_segments: list[dict], batch_start: int,
                  target: TargetLang, n: int = 3) -> list[dict]:
    """``n`` câu ngay trước một lô, làm ngữ cảnh chỉ-đọc.

    Các lô được dịch độc lập, không có phần này thì mạch hội thoại đứt ở mỗi
    ranh giới lô (xưng hô và thuật ngữ trôi dạt).
    """
    ctx = []
    for seg in all_segments[max(0, batch_start - n):batch_start]:
        item = {"id": seg.get("id"), "text": str(seg.get("text", ""))[:300]}
        if seg.get(target.text_field):
            item[target.text_field] = str(seg[target.text_field])[:300]
        ctx.append(item)
    return ctx


def translate_segments(
    segments: list[dict], target: TargetLang, source_lang: str, settings,
    reporter: ProgressReporter | None = None,
    checkpoint_path: str | None = None,
) -> list[dict]:
    """Dịch toàn bộ câu qua máy chủ, theo từng lô, song song.

    Trả về chính danh sách đó, mỗi câu thêm ``target.text_field``. Câu nào
    máy chủ không dịch được (hiếm — đã chia đôi lô ở phía máy chủ) sẽ vắng
    mặt; lớp gọi phát hiện qua số lượng.
    """
    if not segments:
        raise TranslateError("Không có câu nào để dịch")

    from autodub.text.translate_hint import effective_cps

    client = get_client()
    cps = effective_cps(settings)
    context = _context_from_settings(settings)
    run_id = run_id_for(segments, target)

    batch_size = max(1, min(100, int(getattr(settings, "translate_batch_size", 40))))
    batches = [segments[i:i + batch_size] for i in range(0, len(segments), batch_size)]
    checkpoint = TranslateCheckpoint(checkpoint_path, target.text_field)
    workers = min(max(1, int(getattr(settings, "parallel_workers", 4))),
                  len(batches), _WORKERS_CAP)

    logger.info(f"Đang dịch {len(segments)} câu qua VoxDub Cloud "
                f"(mỗi lượt {batch_size} câu, {workers} lượt song song)")

    # Hết Vox thì mọi lô còn lại chắc chắn cũng hỏng — dựng cờ để các luồng
    # khác dừng ngay thay vì đâm đầu vào cùng một bức tường.
    out_of_credit: list[InsufficientCreditError] = []
    stop = threading.Event()

    def _run_batch(index: int, batch: list[dict]) -> list[dict]:
        cached = checkpoint.take(batch)
        if cached is not None:
            return cached
        if stop.is_set():
            raise out_of_credit[0]

        payload = [_payload_segment(s, cps) for s in batch]
        # job_id băm theo NỘI DUNG lô nên gửi lại đúng lô đó là idempotent:
        # máy chủ trả kết quả đã tính phí chứ KHÔNG trừ Vox lần hai. Chính điều
        # đó làm việc thử lại ở đây an toàn về tiền.
        job_id = _batch_job_id(run_id, batch)
        data = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            if reporter is not None:
                reporter.check_cancelled()
            try:
                RATE_LIMITER.acquire()
                data = client.translate(
                    payload,
                    job_id=job_id,
                    source_lang=source_lang,
                    context=context,
                    cps_budget=cps,
                    prev_context=_prev_context(segments, index * batch_size, target),
                    hold_id=HOLD.hold_id,
                )
                break
            except InsufficientCreditError as e:
                out_of_credit.append(e)
                stop.set()
                raise
            except SaasError as e:
                if attempt >= _MAX_ATTEMPTS or not _is_retryable(e):
                    raise TranslateError(str(e)) from e
                base = _BACKOFF_S[min(attempt, len(_BACKOFF_S)) - 1]
                delay = base * random.uniform(0.8, 1.2)
                delay = max(delay, float(getattr(e, "retry_after", 0.0) or 0.0))
                logger.warning(
                    f"  Lô {index + 1} lỗi tạm thời ({e}) — thử lại lần "
                    f"{attempt}/{_MAX_ATTEMPTS - 1} sau {delay:.0f}s")
                _sleep_cancellable(delay, reporter, stop)
                if stop.is_set():
                    raise out_of_credit[0]

        merged = _merge(batch, data.get("segments") or [], target.text_field)
        checkpoint.put(merged)
        return merged

    from concurrent.futures import ThreadPoolExecutor

    done = 0
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = [pool.submit(_run_batch, i, b) for i, b in enumerate(batches)]
        results: list[list[dict]] = []
        for i, fut in enumerate(futures):
            if reporter is not None:
                reporter.check_cancelled()
            results.append(fut.result())
            done += len(batches[i])
            logger.info(f"  Đã dịch {done}/{len(segments)} câu")
            if reporter is not None:
                reporter.emit("translate", "progress",
                              current=done, total=len(segments))
    except BaseException:
        # Hủy hoặc lỗi: không chờ các lô đang bay — trả điều khiển về ngay.
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        pool.shutdown(wait=True)

    if checkpoint.write_errors:
        logger.error(
            f"Sổ dịch tạm ghi lỗi {checkpoint.write_errors} lần — nếu lượt "
            "này bị ngắt, chạy lại sẽ phải dịch lại (máy chủ vẫn trả kết quả "
            "đã tính phí theo job_id nên không tốn Vox thêm, chỉ chậm)")
    checkpoint.discard()
    return [seg for batch in results for seg in batch]


def _merge(batch: list[dict], returned: list[dict], text_field: str) -> list[dict]:
    """Ghép bản dịch máy chủ trả về vào đúng câu gốc, theo ``id``.

    Máy chủ đã chuẩn hóa dấu câu và ghép theo id rồi, ở đây chỉ cần gắn lại
    vào các câu đầy đủ (còn nguyên start/end/slot) của phía máy khách.
    """
    by_id = {}
    for item in returned:
        text = str(item.get(text_field, "") or "").strip()
        if text:
            try:
                by_id[int(item.get("id"))] = text
            except (TypeError, ValueError):
                continue

    merged = []
    missing = []
    for seg in batch:
        text = by_id.get(int(seg["id"]))
        if not text:
            # Máy chủ đã tính phí và cache lô này theo job_id — raise ở đây là
            # ngõ cụt: chạy lại nhận đúng kết quả thiếu đó, kẹt vô hạn trong
            # khi Vox đã tiêu. Giữ nguyên bản gốc cho câu thiếu; chữ nguồn còn
            # sót sẽ được lượt rà soát bắt và sửa sau.
            missing.append(seg.get("id"))
            merged.append({**seg, text_field: str(seg.get("text", ""))})
            continue
        merged.append({**seg, text_field: text})

    if missing:
        logger.warning(
            f"Bản dịch thiếu {len(missing)} câu (id: {missing[:10]}"
            f"{'...' if len(missing) > 10 else ''}) — giữ nguyên bản gốc, "
            "lượt rà soát sẽ xử lý")
    return merged


# --------------------------------------------------- phân tích và rà soát --

def analyze_transcript(segments: list[dict], source_lang: str,
                       video_title: str = "", cache_path: str | None = None,
                       max_lines: int = 240) -> dict | None:
    """Lượt 0 "hiểu video" — tóm tắt, xưng hô, thuật ngữ.

    Kết quả lưu lại trong thư mục dự án nên chạy tiếp không tốn thêm Vox.
    Mọi lỗi ở đây đều không gây hỏng: phân tích thất bại thì dịch như thường.
    """
    import os

    from autodub import securestore

    if cache_path and os.path.exists(cache_path):
        try:
            cached = securestore.read_json_secure(cache_path, HOLD.key)
            logger.info("Dùng lại phân tích ngữ cảnh video từ lần chạy trước")
            return cached
        except Exception:  # noqa: BLE001 — cache hỏng/sai khóa thì phân tích lại
            pass

    texts = [str(s.get("text", "")).strip() for s in segments]
    texts = [t for t in texts if t]
    if not texts:
        return None
    # Transcript quá dài thì lấy mẫu đầu–giữa–cuối: đủ nắm mạch nội dung và
    # nhân vật mà không tốn token vô ích.
    if len(texts) > max_lines:
        third = max_lines // 3
        mid = len(texts) // 2
        texts = (texts[:third] + ["..."]
                 + texts[mid - third // 2:mid + third // 2] + ["..."]
                 + texts[-third:])

    try:
        RATE_LIMITER.acquire()
        analysis = get_client().analyze(
            texts, job_id=f"an-{run_id_for(segments, _DUMMY_TARGET)}",
            source_lang=source_lang, video_title=video_title,
            hold_id=HOLD.hold_id)
    except InsufficientCreditError:
        raise
    except SaasError as e:
        logger.warning(f"Phân tích ngữ cảnh video lỗi ({e}) — dịch như cũ")
        return None
    if not analysis:
        return None

    logger.info(f"Ngữ cảnh video: {str(analysis.get('summary', ''))[:100]}...")
    if cache_path:
        try:
            securestore.write_json_secure(analysis, cache_path, HOLD.key)
        except OSError:
            pass
    return analysis


class _DummyTarget:
    """Chỉ để tính mã lượt cho lượt phân tích (không có text_field thật)."""

    text_field = "analysis"


_DUMMY_TARGET = _DummyTarget()


def apply_analysis(settings, analysis: dict | None):
    """Bản sao Settings với ngữ cảnh phân tích bơm vào các ô còn TRỐNG.

    Người dùng đã điền tay mục nào trong Cài đặt thì mục đó thắng.
    """
    import dataclasses

    if not analysis:
        return settings
    updates: dict = {}
    if not settings.translate_domain and analysis.get("domain"):
        updates["translate_domain"] = str(analysis["domain"]).strip()
    if not settings.translate_context and analysis.get("summary"):
        updates["translate_context"] = str(analysis["summary"]).strip()
    if not settings.translate_pronouns and analysis.get("pronouns"):
        updates["translate_pronouns"] = str(analysis["pronouns"]).strip()
    if not settings.translate_glossary and analysis.get("glossary"):
        items = analysis["glossary"]
        if isinstance(items, list):
            updates["translate_glossary"] = "\n".join(
                str(x).strip() for x in items[:15] if str(x).strip())
    if not settings.translate_style_notes and analysis.get("style_notes"):
        updates["translate_style_notes"] = str(analysis["style_notes"]).strip()
    if not updates:
        return settings
    logger.info("Bơm ngữ cảnh tự phân tích vào prompt dịch: "
                + ", ".join(k.replace("translate_", "") for k in updates))
    return dataclasses.replace(settings, **updates)
