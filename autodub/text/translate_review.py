"""Review pass — soát và dịch lại các câu "nghi vấn" sau lượt dịch chính.

Việc TÌM câu nghi vấn chạy hoàn toàn trên máy, không tốn Vox nào:

- vượt ``max_chars`` của slot quá 25% → gần như chắc chắn tràn slot,
  timeline phải dồn trễ/nén vì đúng câu này
- còn ký tự CJK (lưới cuối — máy chủ đã tự vá nhưng vẫn có thể lọt)
- ngắn bất thường so với nguồn (< 25% ký tự nguồn) → thường là dịch sót ý

Chỉ những câu bị cờ mới được gửi lên máy chủ dịch lại (kèm 2 câu ngữ cảnh
trước/sau), và chỉ những câu THỰC SỰ tốt hơn mới bị tính phí — máy chủ đếm
đúng số câu nó chấp nhận sửa.

Mọi lỗi đều không gây hỏng: rà soát lỗi thì giữ nguyên bản dịch lượt đầu.
"""
from __future__ import annotations

import hashlib

from autodub.languages import TargetLang
from autodub.saas_client import InsufficientCreditError, SaasError, get_client
from autodub.text.translate_common import HOLD, contains_cjk
from autodub.text.translate_hint import effective_cps, payload_segment
from autodub.text.translate_saas import RATE_LIMITER
from autodub.utils import setup_logging

logger = setup_logging("autodub.translate_review")

_OVER_BUDGET_TOLERANCE = 1.25   # vượt max_chars 25% mới tính là tràn
_MIN_SOURCE_RATIO = 0.25        # dịch < 25% độ dài nguồn = nghi sót ý
_MAX_REVIEW_FRACTION = 0.35     # >35% số câu bị cờ ⇒ lỗi hệ thống, bỏ review
_MAX_ITEMS_PER_REQUEST = 60     # trần của máy chủ


def _chunk_job_id(run_id: str, chunk: list[dict]) -> str:
    """Khóa idempotency của một lượt rà soát — băm theo nội dung chunk.

    Danh sách câu bị cờ thay đổi giữa hai lần chạy (bản dịch lượt đầu khác
    đi) thì khóa cũng đổi theo; khóa theo chỉ số chunk sẽ trả nhầm cache của
    một tập câu khác.
    """
    h = hashlib.sha256()
    for item in chunk:
        h.update(f"{item.get('id')}\x1f{item.get('current', '')}\x1e".encode())
    return f"rv-{run_id or 'x'}-{h.hexdigest()[:16]}"


def _flag(seg: dict, text_field: str, cps: float) -> str | None:
    """Lý do nghi vấn của một câu, hoặc None nếu ổn."""
    text = str(seg.get(text_field, "")).strip()
    if not text:
        return None  # đã được các lớp trước xử lý (write_silence)
    if contains_cjk(text):
        return "cjk"
    budget = payload_segment(seg, cps).get("max_chars")
    if budget and len(text) > budget * _OVER_BUDGET_TOLERANCE:
        return "over_budget"
    src = str(seg.get("text", "")).strip()
    if src and len(text) < len(src) * _MIN_SOURCE_RATIO and len(src) > 20:
        return "too_short"
    return None


def review_translations(
    segments: list[dict], target: TargetLang, source_lang: str, settings,
    run_id: str = "",
) -> list[dict]:
    """Soát + dịch lại các câu nghi vấn. Trả về danh sách câu (có thể mới).

    Không sửa tại chỗ — trả về bản sao khi có thay đổi.
    """
    if not getattr(settings, "translate_review", True):
        return segments

    cps = effective_cps(settings)
    flagged = [(i, _flag(s, target.text_field, cps)) for i, s in enumerate(segments)]
    flagged = [(i, r) for i, r in flagged if r]
    if not flagged:
        logger.info("Soát lại bản dịch: mọi câu đều đạt")
        return segments

    by_reason: dict[str, int] = {}
    for _, r in flagged:
        by_reason[r] = by_reason.get(r, 0) + 1
    # Nhãn tiếng Việt cho Nhật ký GUI (log kỹ thuật xem code/console).
    labels = {"over_budget": "hơi dài so với chỗ trống",
              "cjk": "còn sót chữ Trung",
              "too_short": "nghi dịch sót ý"}
    breakdown = ", ".join(f"{v} câu {labels.get(k, k)}" for k, v in by_reason.items())

    if len(flagged) > len(segments) * _MAX_REVIEW_FRACTION:
        # Cờ tràn lan ⇒ vấn đề nằm ở prompt/budget chứ không phải từng câu —
        # dịch lại từng câu chỉ đốt Vox. Ghi nhận và thôi.
        hint = ("video nói nhanh và dày — nếu nghe bị chồng tiếng, giảm "
                "Tốc độ video trong Cài đặt rồi chạy lại"
                if by_reason.get("over_budget", 0) >= len(flagged) * 0.6
                else "xem quality_report.json trong thư mục kết quả")
        logger.warning(
            f"Soát lại bản dịch: {len(flagged)}/{len(segments)} câu cần xem "
            f"({breakdown}) — nhiều quá nên giữ nguyên bản dịch, không sửa "
            f"từng câu. Gợi ý: {hint}.")
        return segments

    logger.info(f"Soát lại bản dịch: {len(flagged)} câu cần sửa "
                f"({breakdown}) — đang nhờ AI dịch lại các câu đó...")

    from autodub.text.translate_saas import _context_from_settings

    def _neighbors(idx: int) -> str:
        rows = []
        for j in range(max(0, idx - 2), min(len(segments), idx + 3)):
            if j == idx:
                continue
            rows.append(f'  {segments[j].get("id")}: '
                        f'{str(segments[j].get("text", ""))[:80]}')
        return "\n".join(rows)

    items = []
    for idx, reason in flagged:
        seg = segments[idx]
        item = {
            "id": int(seg["id"]),
            "reason": reason,
            "text": str(seg.get("text", ""))[:800],
            "current": str(seg.get(target.text_field, ""))[:1200],
            "neighbors": _neighbors(idx)[:1200],
        }
        duration = float(seg.get("duration", 0) or 0)
        if duration > 0:
            item["duration"] = round(duration, 3)
        budget = payload_segment(seg, cps).get("max_chars")
        if budget:
            item["max_chars"] = budget
        items.append(item)

    client = get_client()
    context = _context_from_settings(settings)
    fixed: dict[int, str] = {}
    # Máy chủ nhận tối đa 60 câu mỗi lượt — chia nhỏ nếu vượt.
    for offset in range(0, len(items), _MAX_ITEMS_PER_REQUEST):
        chunk = items[offset:offset + _MAX_ITEMS_PER_REQUEST]
        try:
            RATE_LIMITER.acquire()
            result = client.review(
                chunk,
                job_id=_chunk_job_id(run_id, chunk),
                source_lang=source_lang, context=context, cps_budget=cps,
                hold_id=HOLD.hold_id)
        except InsufficientCreditError:
            # Hết Vox giữa chừng: bản dịch lượt đầu vẫn dùng được, không nên
            # ném lỗi ra làm hỏng cả video vì một bước cải thiện.
            logger.warning("Hết Vox khi soát lại — giữ bản dịch lượt đầu")
            break
        except SaasError as e:
            logger.warning(f"Soát lại bản dịch lỗi ({e}) — giữ bản lượt đầu")
            break
        for item in result:
            text = str(item.get(target.text_field, "") or "").strip()
            if text:
                try:
                    fixed[int(item["id"])] = text
                except (KeyError, TypeError, ValueError):
                    continue

    if not fixed:
        logger.info("Soát lại bản dịch: bản dịch lại không tốt hơn — giữ bản đầu")
        return segments
    logger.info(f"Soát lại bản dịch: đã sửa xong {len(fixed)}/{len(flagged)} câu")
    return [
        ({**s, target.text_field: fixed[int(s["id"])]}
         if int(s["id"]) in fixed else s)
        for s in segments
    ]
