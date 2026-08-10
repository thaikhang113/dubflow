"""Phần dùng chung của luồng dịch: kiểu lỗi, sổ tạm và tiện ích văn bản.

Việc gọi mô hình và đọc JSON đã chuyển hẳn lên máy chủ (xem
``control_server/src/services/ai-gateway.service.js``). Còn lại ở đây là
những thứ chỉ máy khách mới cần: sổ đếm token cho báo cáo chất lượng, sổ lưu
tạm bản dịch theo lô để chạy lại không mất công, và bộ dò chữ Hán sót.
"""
from __future__ import annotations

import json
import os
import re
import threading

from autodub.utils import setup_logging

logger = setup_logging("autodub.translate")

# Chữ Hán (kể cả phần mở rộng A) — bản dịch còn ký tự này là dịch chưa xong.
_CJK_RE = re.compile(r"[㐀-䶿一-鿿]")

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


class TranslateError(Exception):
    """Nơi dịch không trả về kết quả dùng được."""


class UsageCounter:
    """Đếm Vox đã tiêu trong một lượt dịch, an toàn đa luồng.

    Máy chủ trả về ``creditCharged`` và ``balanceAfter`` sau mỗi lượt gọi.
    Cộng dồn ở đây rồi ghi vào ``quality_report.json`` là cách duy nhất để
    người dùng đối chiếu "video này tốn bao nhiêu" với lịch sử ví của họ.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls = 0
        self._vox = 0
        self._balance_after = 0

    def reset(self) -> None:
        with self._lock:
            self._calls = self._vox = self._balance_after = 0

    def add(self, vox: int, balance_after: int = 0) -> None:
        with self._lock:
            self._calls += 1
            self._vox += max(0, int(vox or 0))
            self._balance_after = max(0, int(balance_after or 0))

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "calls": self._calls,
                "vox": self._vox,
                "balance_after": self._balance_after,
            }


# Sổ chung cho cả lượt dịch (phân tích, dịch, rà soát đều cộng vào đây).
USAGE = UsageCounter()


class HoldContext:
    """Hold Vox đang gắn với lượt chạy hiện tại (luồng wizard), đa luồng an toàn.

    Pipeline set trước bước dịch; mọi lượt gọi AI đọc ``hold_id`` từ đây để
    tích lũy usage vào hold thay vì trừ ví thẳng, và securestore đọc ``key``
    để mã hóa file trung gian. Khóa CHỈ sống trong RAM — crash thì chạy lại
    cùng video → cùng run_id → máy chủ cấp lại khóa qua ``get_hold``.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hold_id: str | None = None
        self._key: str | None = None

    def set(self, hold_id: str, key: str) -> None:
        with self._lock:
            self._hold_id = hold_id
            self._key = key

    def clear(self) -> None:
        with self._lock:
            self._hold_id = self._key = None

    @property
    def hold_id(self) -> str | None:
        with self._lock:
            return self._hold_id

    @property
    def key(self) -> str | None:
        with self._lock:
            return self._key

    @property
    def active(self) -> bool:
        with self._lock:
            return bool(self._hold_id and self._key)


# Hold của lượt chạy hiện tại (rỗng ở luồng batch/legacy — mọi thứ như cũ).
HOLD = HoldContext()


def contains_cjk(text: str) -> bool:
    """Chuỗi này còn sót chữ Hán hay không."""
    return bool(_CJK_RE.search(str(text or "")))


class TranslateCheckpoint:
    """Sổ lưu tạm bản dịch theo từng lô, để chạy lại không dịch lại từ đầu.

    Dịch một video dài tốn hàng chục lượt gọi API. Hết hạn mức hay rớt mạng ở
    lô thứ 40/50 mà vứt hết 39 lô đã xong là đốt tiền và thời gian. Mỗi lô
    dịch xong được ghi ngay xuống đây (ghi nguyên tử); lượt chạy sau đọc lại
    và bỏ qua các câu đã có. Dịch trọn vẹn thì xóa sổ — tệp kết quả cuối vẫn
    do lớp gọi ghi, đúng giao kèo "chỉ lưu khi cả lượt thành công".

    Khóa theo ``id`` câu và đối chiếu cả câu gốc, nên sổ cũ của một bản
    nghe-chép khác (đã sửa tay, đã nghe lại...) không bị lấy nhầm.
    """

    def __init__(self, path: str | None, text_field: str) -> None:
        self.path = path
        self.text_field = text_field
        self._lock = threading.Lock()
        self._items: dict[str, dict] = {}
        #: Số lần ghi sổ thất bại — đọc sau lượt dịch để giải thích vì sao
        #: chạy lại không tận dụng được gì.
        self.write_errors = 0
        if not path or not os.path.exists(path):
            return
        try:
            # Sổ tạm chứa bản dịch trả phí — luồng wizard mã hóa nó khi hold
            # chưa chốt. read_json_secure tự nhận biết file thường/mã hóa.
            from autodub import securestore

            data = securestore.read_json_secure(path, HOLD.key)
            if (isinstance(data, dict)
                    and data.get("text_field") == text_field
                    and isinstance(data.get("items"), dict)):
                self._items = {
                    k: v for k, v in data["items"].items()
                    if isinstance(v, dict) and v.get("text")
                }
                if self._items:
                    logger.info(f"Đọc sổ dịch tạm: {len(self._items)} câu "
                                "đã dịch từ lượt trước")
        except Exception as e:  # noqa: BLE001 — sổ hỏng/sai khóa đều dịch lại
            logger.warning(f"Sổ dịch tạm hỏng ({e}) — dịch lại từ đầu")
            self._items = {}

    @staticmethod
    def _key(seg: dict) -> str:
        return str(seg.get("id"))

    def take(self, batch: list[dict]) -> list[dict] | None:
        """Bản dịch đã lưu của cả lô, hoặc None nếu lô còn câu chưa dịch."""
        merged: list[dict] = []
        for seg in batch:
            item = self._items.get(self._key(seg))
            if item is None or item.get("src") != seg.get("text"):
                return None
            merged.append({**seg, self.text_field: item["text"]})
        return merged

    def put(self, merged_batch: list[dict]) -> None:
        """Ghi một lô vừa dịch xong xuống đĩa (nguyên tử, an toàn đa luồng)."""
        if not self.path:
            return
        with self._lock:
            for seg in merged_batch:
                self._items[self._key(seg)] = {
                    "src": seg.get("text"),
                    "text": seg.get(self.text_field, ""),
                }
            try:
                from autodub import securestore

                # HOLD active → sổ tạm nằm trên đĩa dưới dạng mã hóa.
                securestore.write_json_secure(
                    {"text_field": self.text_field, "items": self._items},
                    self.path, HOLD.key)
            except OSError as e:
                # Không lưu được sổ tạm thì lượt dịch vẫn phải chạy tiếp —
                # nhưng ở mức error, vì đây chính là lý do "chạy lại vẫn phải
                # dịch lại từ đầu": không có sổ thì không có gì để dùng lại.
                self.write_errors += 1
                logger.error(f"Không ghi được sổ dịch tạm ({e}) — chạy lại "
                             "sẽ phải dịch lại các lô này")

    def discard(self) -> None:
        """Xóa sổ khi cả lượt dịch đã thành công trọn vẹn."""
        if not self.path:
            return
        try:
            os.remove(self.path)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning(f"Không xóa được sổ dịch tạm: {e}")


def strip_fences(text: str) -> str:
    """Bỏ khối ```json ... ``` mà một số mô hình vẫn bọc quanh câu trả lời."""
    text = str(text or "").strip()
    text = _FENCE_RE.sub("", text)
    return text.strip()


def _slice_to_payload(text: str) -> str:
    """Cắt lấy phần từ dấu mở ngoặc đầu tiên tới dấu đóng cuối cùng.

    Mô hình hay chèn thêm một câu dẫn ("Here is the JSON:") hoặc một dòng kết.
    Phần JSON thật luôn nằm giữa cặp ngoặc ngoài cùng.
    """
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        return text
    start = min(starts)
    end = max(text.rfind("}"), text.rfind("]"))
    return text[start:end + 1] if end > start else text[start:]


def repair_json(text: str) -> str:
    """Vá một khối JSON bị cắt giữa chừng để còn đọc được phần đã có.

    Câu trả lời chạm trần token bị đứt ngang: có thể đứt giữa một chuỗi, và
    chắc chắn thiếu các dấu đóng ngoặc. Hàm này đóng nốt chúng theo đúng thứ
    tự đã mở. Câu cuối cùng bị đứt sẽ hỏng, nhưng phần trước đó vẫn cứu được.
    """
    text = _slice_to_payload(strip_fences(text)).rstrip()
    if not text:
        return text

    stack: list[str] = []
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack:
            stack.pop()

    if in_string:
        text += '"'
    # Bỏ phần đuôi dở dang: dấu phẩy treo, một khóa chưa có giá trị, hoặc
    # một khóa bị đứt trước cả dấu hai chấm (vd ``{"id": 78, "text_``).
    text = re.sub(r",\s*$", "", text)
    text = re.sub(r',\s*"[^"]*"\s*:?\s*$', "", text)
    text = re.sub(r'\{\s*"[^"]*"\s*:?\s*$', "{", text)
    return text + "".join(reversed(stack))


def parse_response_segments(content: str) -> list[dict]:
    """Đọc câu trả lời của mô hình thành danh sách câu.

    Chấp nhận cả ``{"segments": [...]}`` lẫn một mảng trần, có hay không có
    khối ```json bọc ngoài. Hỏng hoàn toàn thì ném :class:`TranslateError`
    kèm một mẩu nội dung để người dùng còn biết chuyện gì xảy ra.
    """
    raw = strip_fences(content)
    for candidate in (raw, _slice_to_payload(raw), repair_json(raw)):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict):
            data = data.get("segments", data.get("data", []))
        if isinstance(data, list):
            return [s for s in data if isinstance(s, dict)]
    raise TranslateError(
        "Không đọc được kết quả dịch (JSON hỏng): "
        + raw[:200].replace("\n", " ")
    )


def merge_translations(batch: list[dict], returned: list[dict],
                       text_field: str) -> list[dict]:
    """Ghép bản dịch trả về vào đúng câu gốc, theo ``id``.

    Trả về danh sách BẢN SAO của ``batch`` đã có thêm ``text_field``; câu gốc
    không bị đụng tới, nên một lô hỏng giữa chừng không làm bẩn dữ liệu.
    Thiếu câu nào thì ném lỗi để lớp trên chia đôi lô rồi thử lại.
    """
    from autodub.text.translate_hint import ensure_terminal_punct

    by_id: dict = {}
    for item in returned:
        seg_id = item.get("id")
        text = str(item.get(text_field, "") or "").strip()
        if seg_id is None or not text:
            continue
        try:
            by_id[int(seg_id)] = text
        except (TypeError, ValueError):
            by_id[str(seg_id)] = text

    # Mô hình bỏ mất id nhưng trả đúng số câu, đúng thứ tự — chấp nhận và
    # ghép theo vị trí, còn hơn ném đi cả một lô đã dịch xong.
    if not by_id and len(returned) == len(batch):
        by_id = {int(seg.get("id")): str(item.get(text_field, "") or "").strip()
                 for seg, item in zip(batch, returned)
                 if str(item.get(text_field, "") or "").strip()}

    merged: list[dict] = []
    missing: list = []
    for seg in batch:
        seg_id = seg.get("id")
        text = by_id.get(seg_id)
        if text is None:
            try:
                text = by_id.get(int(seg_id))
            except (TypeError, ValueError):
                text = None
        if not text:
            missing.append(seg_id)
            continue
        merged.append({**seg, text_field: ensure_terminal_punct(text)})

    if missing:
        raise TranslateError(
            f"Bản dịch thiếu {len(missing)} câu (id: {missing[:10]}"
            f"{'...' if len(missing) > 10 else ''})"
        )
    return merged
