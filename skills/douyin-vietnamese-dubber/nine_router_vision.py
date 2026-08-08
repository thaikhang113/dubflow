#!/usr/bin/env python3
"""
nine_router_vision.py — Shared 9router MiniMax-M3 multimodal vision client.

Dùng cho hai mục đích trong pipeline OpenClaw:
  1. OCR transcript subtitle gốc (engine = 9router_vision) — đọc text Trung trong frame.
  2. Detect band subtitle Trung (SUBTITLE_MASK_DETECT_ENGINE=9router_vision) — tìm bbox dòng chữ Trung.

Cấu hình qua env (phù hợp cách run.sh truyền env):
  NINEROUTER_API_BASE          / OCR_VISION_API_BASE        base url OpenAI-compatible (vd http://127.0.0.1:20128/v1)
  OCR_VISION_API_KEY / NINEROUTER_API_KEY                  bearer key (dedicated key first)
  OCR_VISION_MODEL / NINEROUTER_VISION_MODEL / OPENCLAW_VISION_MODEL
                                                        vision model id (vd ollama/minimax-m3:cloud)
  OCR_VISION_PROVIDER                                         "ninerouter" (mặc định), "ollama", hoặc "local"

Quan trọng:
  - Dùng stream:false để 9router trả JSON gọn trong choices[].message.content (probe thực tế
    cho thấy non-stream không kèm reasoning_content; stream mới có).
  - Nếu endpoint trả lỗi HTTP/timeout/rỗng/payload không hỗ trợ ảnh => raise VisionError với
    reason rõ ràng, để caller fallback PaddleOCR/CV/ASR mà không phá pipeline.
  - Parse JSON cẩn thận: gọt ``` fence, lấy khối {...} đầu tiên.
"""
import base64
import json
import os
import re
import urllib.error
import urllib.request


DEFAULT_TIMEOUT = 60


class VisionError(Exception):
    """Lỗi gọi vision API. Caller bắt để fallback, KHÔNG re-raise để giữ pipeline chạy."""

    def __init__(self, reason, status=None, detail=None):
        super().__init__(reason)
        self.reason = reason
        self.status = status
        self.detail = detail


def _pick(*names, default=None):
    for n in names:
        v = os.environ.get(n)
        if v is not None and v != "":
            return v
    return default


def resolve_config():
    """Trả dict {api_base, api_key, model, provider} từ env."""
    # OCR routing must not inherit OPENCLAW_AI_PROVIDER: translation may be
    # Ollama while OCR remains on 9Router vision (or vice versa).
    provider = _pick("OCR_VISION_PROVIDER", "NINEROUTER_VISION_PROVIDER",
                     "OPENCLAW_VISION_PROVIDER", default="ninerouter").strip().lower()
    if provider in ("9router", "ninerouter"):
        provider = "ninerouter"
    elif provider not in ("ollama", "local", "paddleocr", "cv"):
        provider = "ninerouter"
    # Do not inherit NINEROUTER_MODEL here: it commonly selects the text/chat
    # model and may be a route that cannot accept image content.
    if provider == "ollama":
        model = _pick("OCR_VISION_MODEL", "OLLAMA_VISION_MODEL", "OLLAMA_MODEL",
                      default="ollama/minimax-m3:cloud")
    else:
        model = _pick("OCR_VISION_MODEL", "NINEROUTER_VISION_MODEL", "OPENCLAW_VISION_MODEL",
                      default="ollama/minimax-m3:cloud")
    if provider == "ollama":
        api_base = _pick("OCR_VISION_API_BASE", "OLLAMA_API_BASE",
                          default="http://127.0.0.1:11434")
        return {"api_base": api_base, "api_key": "", "model": model, "provider": provider}
    if provider in ("local", "paddleocr", "cv"):
        api_base = _pick("OCR_VISION_API_BASE", default="")
        return {"api_base": api_base, "api_key": "", "model": model, "provider": "local"}
    api_key = _pick("OCR_VISION_API_KEY", "NINEROUTER_API_KEY", default="")
    api_base = _pick("OCR_VISION_API_BASE", "NINEROUTER_API_BASE",
                      default="http://127.0.0.1:20128/v1")
    return {"api_base": api_base, "api_key": api_key, "model": model, "provider": provider}


def image_to_data_url(image_path_or_bytes, mime="image/jpeg"):
    """Encode ảnh (đường dẫn hoặc bytes) thành data URL base64."""
    if isinstance(image_path_or_bytes, (bytes, bytearray)):
        raw = bytes(image_path_or_bytes)
    else:
        with open(image_path_or_bytes, "rb") as f:
            raw = f.read()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _extract_json_obj(text):
    """Lấy khối JSON object đầu tiên trong text (gọt fence ```)."""
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start:end + 1]
    try:
        return json.loads(cleaned)
    except Exception:
        return None


def _parse_content(resp_json):
    """Lấy content string từ response OpenAI-compatible hoặc Ollama /api/chat."""
    if not isinstance(resp_json, dict):
        return None
    choices = resp_json.get("choices")
    if isinstance(choices, list) and choices:
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if isinstance(content, list):
            # Một số backend trả content dạng list parts
            parts = []
            for p in content:
                if isinstance(p, dict):
                    parts.append(p.get("text") or "")
                else:
                    parts.append(str(p))
            content = "".join(parts)
        if content:
            return str(content).strip()
    msg = resp_json.get("message")
    if isinstance(msg, dict) and msg.get("content"):
        return str(msg["content"]).strip()
    return None


def vision_chat_json(messages, *, timeout=DEFAULT_TIMEOUT, max_tokens=256):
    """
    Gọi 9router multimodal với messages đã dựng sẵn, ép trả JSON.
    Trả dict parse được, hoặc raise VisionError.
    messages có dạng OpenAI: [{"role":"user","content":[{"type":"text",...},{"type":"image_url",...}]}]
    """
    cfg = resolve_config()
    api_base = cfg["api_base"].rstrip("/")
    if cfg["provider"] == "ollama":
        url = api_base + "/api/chat"
        payload = {
            "model": cfg["model"],
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {"num_predict": max_tokens, "temperature": 0.1},
        }
        headers = {"Content-Type": "application/json"}
    else:
        url = api_base + "/chat/completions"
        payload = {
            "model": cfg["model"],
            "messages": messages,
            "stream": False,
            "think": False,
            "temperature": 0.1,
            "max_tokens": max_tokens,
        }
        headers = {"Content-Type": "application/json"}
        if cfg["api_key"]:
            headers["Authorization"] = "Bearer " + cfg["api_key"]

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        snippet = ""
        try:
            snippet = exc.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        # Payload ảnh không hỗ trợ thường là 400/500 — đánh dấu rõ để fallback.
        if exc.code in (400, 415):
            raise VisionError("vision_payload_unsupported", status=exc.code, detail=snippet)
        raise VisionError(f"http_{exc.code}", status=exc.code, detail=snippet)
    except urllib.error.URLError as exc:
        raise VisionError("network_error", detail=str(exc))
    except Exception as exc:
        raise VisionError("request_failed", detail=str(exc)[:200])

    try:
        resp_json = json.loads(body)
    except Exception:
        raise VisionError("invalid_json_response", status=status, detail=body[:300])

    # Endpoint có thể trả error JSON ngay cả khi HTTP 200
    if isinstance(resp_json, dict) and resp_json.get("error"):
        err = resp_json["error"]
        msg = err.get("message") if isinstance(err, dict) else str(err)
        reason = "vision_payload_unsupported" if "image" in str(msg).lower() or "500" in str(msg) else "api_error"
        raise VisionError(reason, status=status, detail=str(msg)[:300])

    content = _parse_content(resp_json)
    if not content:
        raise VisionError("empty_content", status=status)
    obj = _extract_json_obj(content)
    if obj is None:
        raise VisionError("unparsable_json", detail=content[:300])
    return obj


# ---------------------------------------------------------------------------
# Higher-level helpers dùng cho OCR transcript + band detect.
# ---------------------------------------------------------------------------

def _bbox_valid(bbox, width, height):
    """bbox [x1,y1,x2,y2] hợp lệ (có diện tích dương, trong khung)."""
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return False
    try:
        x1, y1, x2, y2 = [float(v) for v in bbox]
    except (TypeError, ValueError):
        return False
    if x2 <= x1 or y2 <= y1:
        return False
    if x1 < 0 or y1 < 0 or x2 > width or y2 > height:
        # cho phép clip nhẹ rồi re-validate ở caller; chỉ reject hẳn nếu nằm ngoài hoàn toàn
        if x2 <= 0 or y2 <= 0 or x1 >= width or y1 >= height:
            return False
    return True


def ask_has_subtitle_text(image_path, *, width, height, prompt=None, timeout=DEFAULT_TIMEOUT):
    """
    Gửi 1 frame/crop ảnh cho AI, hỏi: có subtitle Trung không, text là gì, bbox đâu.
    Trả dict:
      {"has_subtitle": bool, "text": str, "bbox": [x1,y1,x2,y2]|None,
       "confidence": float, "raw": obj}
    Raise VisionError nếu lỗi -> caller fallback.
    """
    if prompt is None:
        prompt = (
            "Đây là một khung (frame/crop) dưới của video có thể chứa phụ đề tiếng Trung. "
            "Kiểm tra xem có chữ phụ đề Trung (Hán) nổi bật không. "
            "Chỉ trả về JSON hợp lệ, đúng định dạng, không giải thích thêm:\n"
            '{"has_subtitle": true|false, "text": "chuỗi chữ Hán nếu có, rỗng nếu không", '
            '"bbox": [x1,y1,x2,y2] toạ độ pixel của dòng chữ trong ảnh (null nếu không có), '
            '"confidence": 0.0-1.0}'
        )
    data_url = image_to_data_url(image_path)
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_url}},
        ],
    }]
    obj = vision_chat_json(messages, timeout=timeout)

    has_sub = bool(obj.get("has_subtitle"))
    text = str(obj.get("text") or "")
    text = re.sub(r"\s+", "", text)  # khớp cách clean_text của Paddle flow
    bbox = obj.get("bbox")
    if isinstance(bbox, list) and len(bbox) == 4:
        bbox = [int(round(float(v))) if v is not None else 0 for v in bbox]
        if not _bbox_valid(bbox, width, height):
            bbox = None
    else:
        bbox = None
    try:
        conf = float(obj.get("confidence"))
        if conf < 0 or conf > 1:
            conf = 0.5
    except (TypeError, ValueError):
        conf = 0.5
    # Chỉ coi là có subtitle khi có text Hán (bảo vệ khỏi has_subtitle=true mà text rỗng).
    has_cjk = bool(re.search(r"[一-鿿]", text))
    if has_sub and not has_cjk:
        has_sub = False
    if not has_sub:
        text = ""
    return {
        "has_subtitle": has_sub,
        "text": text,
        "bbox": bbox,
        "confidence": conf,
        "raw": obj,
    }


def detect_subtitle_frames(frames, *, timeout=DEFAULT_TIMEOUT):
    """
    AI gate: duyệt list frame, trả list các frame CÓ subtitle Trung (xác nhận bằng AI).
    Mỗi entry: {"frame": path, "text": str, "confidence": float}.
    AI chỉ xác nhận có/không + đọc text; bbox chính xác sẽ do CV detector của caller
    khoanh trên chính các frame này (M3 không đáng tin cho toạ độ pixel).

    Không raise: nếu lỗi payload không hỗ trợ -> trả reason để caller fallback toàn bộ.
    Trả dict {"confirmed": [...], "reason": str|None, "detail": str|None}.
    """
    prompt = (
        "Đây là một khung (frame) của video. Kiểm tra xem có dòng phụ đề tiếng Trung "
        "(chữ Hán) nổi bật ở vùng dưới khung không. Chỉ trả JSON hợp lệ, không giải thích:\n"
        '{"has_subtitle": true|false, "text": "chuỗi chữ Hán nếu có, rỗng nếu không", '
        '"confidence": 0.0-1.0}'
    )
    confirmed = []
    reasons = []
    for fp in frames:
        # Lấy kích thước thật để validate bbox/text sau này; AI không cần biết size.
        try:
            from PIL import Image
            with Image.open(fp) as im:
                w, h = im.size
        except Exception:
            w, h = 1920, 1080
        try:
            r = ask_has_subtitle_text(fp, width=w, height=h, prompt=prompt, timeout=timeout)
        except VisionError as exc:
            if exc.reason == "vision_payload_unsupported":
                return {"confirmed": [], "reason": "vision_payload_unsupported",
                        "detail": exc.detail}
            reasons.append(exc.reason)
            continue
        if r["has_subtitle"]:
            confirmed.append({"frame": fp, "text": r["text"], "confidence": r["confidence"]})
    if not confirmed:
        reason = reasons[0] if reasons else "no_subtitle_detected"
        return {"confirmed": [], "reason": reason, "detail": None}
    return {"confirmed": confirmed, "reason": None, "detail": None}


def is_enabled(default=False):
    """Helper: engine 9router_vision có nên dùng làm mặc định không."""
    val = _pick("SUBTITLE_OCR_ENGINE", "OCR_TRANSCRIPT_ENGINE", default="")
    if val:
        return val.strip().lower() in ("9router_vision", "9router-vision", "vision")
    # Cho mask detect
    val2 = _pick("SUBTITLE_MASK_DETECT_ENGINE", "SUBTITLE_BAND_DETECT_ENGINE", default="")
    if val2:
        return val2.strip().lower() in ("9router_vision", "9router-vision", "vision")
    return default
