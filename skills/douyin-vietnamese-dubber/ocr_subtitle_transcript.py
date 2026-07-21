#!/usr/bin/env python3
import argparse
import json
import os
import re
import signal
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image
try:
    import numpy as np
except Exception:
    np = None

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

# Timeout toàn bộ bước OCR transcript (SIGALRM). Khi kích hoạt, raise TimeoutError
# để các loop bắt và trả partial samples thay vì bị `timeout` shell kill mù.
class OcrTranscriptTimeout(Exception):
    """Raised when the total OCR transcript budget is exceeded."""

# Vision OCR engine (9router MiniMax M3) — import lười để không phụ thuộc khi dùng paddle.
try:
    import nine_router_vision as _nrv
except Exception:
    _nrv = None


def seconds_to_srt(ts: float) -> str:
    ts = max(0.0, float(ts))
    hh = int(ts // 3600)
    ts -= hh * 3600
    mm = int(ts // 60)
    ts -= mm * 60
    ss = int(ts)
    ms = int(round((ts - ss) * 1000))
    if ms >= 1000:
        ss += 1
        ms = 0
    return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", "", text or "")
    text = re.sub(r"^[\W_]+|[\W_]+$", "", text, flags=re.UNICODE)
    return text.strip()


def text_similarity(a: str, b: str) -> float:
    a = clean_text(a)
    b = clean_text(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    aset = set(a)
    bset = set(b)
    return len(aset & bset) / max(1, len(aset | bset))


def create_ocr(lang: str):
    from paddleocr import PaddleOCR
    attempts = [
        {"lang": lang, "use_textline_orientation": False},
        {"lang": lang, "use_angle_cls": False},
        {"lang": lang},
    ]
    errors = []
    for kwargs in attempts:
        try:
            return PaddleOCR(**kwargs), kwargs
        except Exception as exc:
            errors.append(f"{kwargs}: {exc!r}")
    raise RuntimeError("PaddleOCR init failed: " + " | ".join(errors))


def ocr_predict(ocr, image_path: Path):
    if hasattr(ocr, "predict"):
        try:
            return ocr.predict(str(image_path))
        except Exception:
            pass
    try:
        return ocr.ocr(str(image_path), cls=False)
    except TypeError:
        return ocr.ocr(str(image_path))


def parse_result(result, min_confidence: float):
    items = []
    for page in result or []:
        if isinstance(page, dict):
            texts = page.get("rec_texts") or []
            scores = page.get("rec_scores") or []
            boxes = page.get("rec_boxes")
            if boxes is None:
                boxes = page.get("dt_boxes")
            if boxes is None:
                boxes = []
            for idx, text in enumerate(texts):
                score = float(scores[idx]) if idx < len(scores) else 1.0
                if score < min_confidence:
                    continue
                clean = clean_text(str(text))
                if not clean or not re.search(r"[\u4e00-\u9fff]", clean):
                    continue
                box = None
                if idx < len(boxes):
                    raw = boxes[idx].tolist() if hasattr(boxes[idx], "tolist") else boxes[idx]
                    if len(raw) == 4 and not isinstance(raw[0], (list, tuple)):
                        box = [int(float(v)) for v in raw]
                items.append({"text": clean, "confidence": score, "bbox": box})
            continue
        for row in page or []:
            if not row or len(row) < 2:
                continue
            meta = row[1]
            text = clean_text(str(meta[0] if isinstance(meta, (list, tuple)) else meta))
            score = float(meta[1]) if isinstance(meta, (list, tuple)) and len(meta) > 1 else 1.0
            if score >= min_confidence and re.search(r"[\u4e00-\u9fff]", text):
                items.append({"text": text, "confidence": score, "bbox": None})
    return items


def best_text(items):
    if not items:
        return "", 0.0, None
    # Prefer longest confident Chinese line, then join close candidates if OCR split the subtitle.
    items = sorted(items, key=lambda it: (len(it["text"]), it["confidence"]), reverse=True)
    selected = items[:2]
    text = "".join(it["text"] for it in selected if it["text"])
    if len(selected) == 1:
        text = selected[0]["text"]
    conf = sum(it["confidence"] for it in selected) / max(1, len(selected))
    boxes = [it["bbox"] for it in selected if it.get("bbox")]
    bbox = None
    if boxes:
        bbox = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
    return clean_text(text), conf, bbox

def has_subtitle_like_pixels(image: Image.Image, min_ratio: float, min_pixels: int):
    """Fast prefilter so PaddleOCR is only called on likely subtitle frames."""
    if min_ratio <= 0 and min_pixels <= 0:
        return True
    if np is not None:
        arr = np.asarray(image.convert("RGB"))
        max_ch = arr.max(axis=2)
        min_ch = arr.min(axis=2)
        bright = max_ch >= 178
        low_spread = (max_ch - min_ch) <= 72
        yellowish = (arr[:, :, 0] >= 170) & (arr[:, :, 1] >= 145) & (arr[:, :, 2] <= 150)
        mask = bright & (low_spread | yellowish)
        count = int(mask.sum())
        ratio = count / max(1, mask.size)
        return count >= min_pixels and ratio >= min_ratio
    gray = image.convert("L")
    hist = gray.histogram()
    count = sum(hist[178:])
    ratio = count / max(1, image.size[0] * image.size[1])
    return count >= min_pixels and ratio >= min_ratio


def vision_available():
    return _nrv is not None


# --- Bounded fast mode: budget toàn bước OCR transcript (SIGALRM) ---
# Khi budget hết, các loop đọc _budget_expired() và thoát sớm, trả partial samples
# thay vì bị shell `timeout` kill mù → report nghèo {"status":"failed","exit":124}.
_BUDGET_DEADLINE = None
_BUDGET_EXPIRED = False


def _start_budget(seconds: float):
    """Cài SIGALRM với budget `seconds`. <=0 nghĩa là không giới hạn."""
    global _BUDGET_DEADLINE, _BUDGET_EXPIRED
    _BUDGET_EXPIRED = False
    if not seconds or seconds <= 0:
        _BUDGET_DEADLINE = None
        return
    # SIGALRM chỉ hoạt động trên main thread; pipeline chạy python trực tiếp nên OK.
    try:
        signal.signal(signal.SIGALRM, _budget_handler)
        signal.setitimer(signal.ITIMER_REAL, float(seconds))
        _BUDGET_DEADLINE = seconds
    except (ValueError, OSError):
        # Không phải main thread hoặc platform không hỗ trợ → bỏ qua budget.
        _BUDGET_DEADLINE = None


def _clear_budget():
    global _BUDGET_DEADLINE, _BUDGET_EXPIRED
    if _BUDGET_DEADLINE is not None:
        try:
            signal.setitimer(signal.ITIMER_REAL, 0)
        except (ValueError, OSError):
            pass
    _BUDGET_DEADLINE = None
    _BUDGET_EXPIRED = False


def _budget_handler(signum, frame):
    global _BUDGET_EXPIRED
    _BUDGET_EXPIRED = True
    raise OcrTranscriptTimeout("ocr_transcript_budget_exceeded")


def _budget_expired() -> bool:
    return _BUDGET_EXPIRED


def ocr_vision_sample(image_path: Path, roi_top: float, roi_bottom: float, prefilter_min_ratio: float,
                      prefilter_min_pixels: int, *, timeout=None):
    """
    Đọc text subtitle Trung trên 1 frame bằng AI vision (9router MiniMax M3).
    Crop ROI dưới video, prefilter pixel (giống paddle flow), gửi crop cho AI.
    Trả (text, confidence) hoặc (None, reason_string) khi không có subtitle/lỗi.
    """
    if not vision_available():
        return None, "vision_module_missing"
    image = Image.open(image_path).convert("RGB")
    w, h = image.size
    y1 = max(0, min(h - 1, int(h * roi_top)))
    y2 = max(y1 + 1, min(h, int(h * roi_bottom)))
    crop = image.crop((0, y1, w, y2))
    if not has_subtitle_like_pixels(crop, prefilter_min_ratio, prefilter_min_pixels):
        return None, "prefilter_skip"
    try:
        r = _nrv.ask_has_subtitle_text(image_path, width=w, height=h, timeout=timeout or _nrv.DEFAULT_TIMEOUT)
    except OcrTranscriptTimeout:
        raise
    except Exception as exc:
        reason = getattr(exc, "reason", None) or "vision_error"
        detail = getattr(exc, "detail", None)
        return None, f"{reason}:{detail}" if detail else reason
    if not r["has_subtitle"]:
        return None, "no_subtitle"
    text = clean_text(r["text"])
    if not text or not re.search(r"[一-鿿]", text):
        return None, "no_cjk"
    return text, float(r["confidence"])


def write_srt(path: Path, segments):
    out = []
    for idx, seg in enumerate(segments, 1):
        out.append(str(idx))
        out.append(f"{seconds_to_srt(seg['start'])} --> {seconds_to_srt(seg['end'])}")
        out.append(seg["text"])
        out.append("")
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def merge_samples(samples, fps: float, merge_gap: float, lead_in: float, hold_out: float):
    segments = []
    active = None
    for sample in samples:
        text = sample["text"]
        if active and (sample["time"] - active["last_time"] <= merge_gap) and text_similarity(text, active["text"]) >= 0.55:
            if len(text) > len(active["text"]):
                active["text"] = text
            active["end"] = sample["time"] + 1.0 / fps
            active["last_time"] = sample["time"]
            active["confidences"].append(sample["confidence"])
            active["sample_count"] += 1
            continue
        if active:
            segments.append(active)
        active = {
            "start": sample["time"],
            "end": sample["time"] + 1.0 / fps,
            "last_time": sample["time"],
            "text": text,
            "confidences": [sample["confidence"]],
            "sample_count": 1,
        }
    if active:
        segments.append(active)
    cleaned = []
    previous_text = ""
    for seg in segments:
        text = clean_text(seg["text"])
        if not text or text_similarity(text, previous_text) >= 0.96:
            if cleaned:
                cleaned[-1]["end"] = max(cleaned[-1]["end"], seg["end"] + hold_out)
            continue
        cleaned.append({
            "start": max(0.0, seg["start"] - lead_in),
            "end": max(seg["start"] + 0.2, seg["end"] + hold_out),
            "text": text,
            "confidence": sum(seg["confidences"]) / max(1, len(seg["confidences"])),
            "sample_count": seg["sample_count"],
        })
        previous_text = text
    return cleaned


def extract_frames(video, tmp_dir, fps, start, duration):
    """ffmpeg cắt frame theo fps, trả list frame path sắp xếp theo index."""
    pattern = tmp_dir / "frame-%06d.jpg"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    if start > 0:
        cmd.extend(["-ss", f"{start:.3f}"])
    cmd.extend(["-i", str(video)])
    if duration > 0:
        cmd.extend(["-t", f"{duration:.3f}"])
    cmd.extend(["-vf", f"fps={fps}", "-q:v", "3", str(pattern)])
    subprocess.run(cmd, check=True)
    return sorted(tmp_dir.glob("frame-*.jpg"))


def run_paddle_on_frames(frames, args, ocr):
    """OCR bằng PaddleOCR trên các frame đã crop ROI + prefilter. Trả (samples, errors, skipped)."""
    samples = []
    errors = []
    skipped = 0
    with TemporaryDirectory(prefix="openclaw-ocr-crop-") as crop_tmp:
        crop_dir = Path(crop_tmp)
        for index, frame in enumerate(frames):
            if _budget_expired():
                break
            ts = args.start + index / args.fps
            try:
                image = Image.open(frame).convert("RGB")
                w, h = image.size
                y1 = max(0, min(h - 1, int(h * args.roi_top)))
                y2 = max(y1 + 1, min(h, int(h * args.roi_bottom)))
                crop = crop_dir / f"crop-{index:06d}.jpg"
                cropped = image.crop((0, y1, w, y2))
                if not has_subtitle_like_pixels(cropped, args.prefilter_min_ratio, args.prefilter_min_pixels):
                    skipped += 1
                    continue
                cropped.save(crop, quality=92)
                items = parse_result(ocr_predict(ocr, crop), args.min_confidence)
                text, confidence, bbox = best_text(items)
                if text:
                    samples.append({"time": ts, "text": text, "confidence": confidence, "bbox": bbox})
            except OcrTranscriptTimeout:
                errors.append({"time": ts, "error": "ocr_transcript_budget_exceeded"})
                break
            except Exception as exc:
                errors.append({"time": ts, "error": repr(exc)[:300]})
    return samples, errors, skipped


def _roi_signature(frame_path, roi_top, roi_bottom):
    """Hash nhỏ của vùng ROI để phát hiện frame kế giống nhau (subtitle không đổi)."""
    try:
        image = Image.open(frame_path).convert("RGB")
        w, h = image.size
        y1 = max(0, min(h - 1, int(h * roi_top)))
        y2 = max(y1 + 1, min(h, int(h * roi_bottom)))
        # Co nhỏ về 32x8 để hash nhanh, nhạy với thay đổi chữ.
        small = image.crop((0, y1, w, y2)).resize((32, 8))
        if np is not None:
            arr = np.asarray(small)
            # Đơn giản hoá: dấu hiệu luminance trung bình mỗi ô.
            return tuple(int(v) for v in arr.mean(axis=(0, 1)).reshape(-1))
        return small.tobytes()[:64]
    except OcrTranscriptTimeout:
        raise
    except Exception:
        return None


def run_vision_on_frames(frames, args, *, min_min_confidence=0.45, dedup=True, vision_timeout=None):
    """
    OCR bằng AI vision (9router MiniMax M3). AI đọc text trên frame (crop ROI nội bộ).
    Trả (samples, errors, skipped, reasons).
    reasons: dict lý do skip/fail để caller quyết định fallback.
    dedup: nếu ROI frame kế giống frame trước (hash gần nhau), giữ text cũ thay vì gọi API lại
           để giảm số request (subtitle thường đứng yên nhiều giây).
    vision_timeout: timeout per-call (giây) cho ask_has_subtitle_text. None = default module.
    """
    samples = []
    errors = []
    skipped = 0
    reasons = {}
    prev_sig = None
    prev_text = None
    prev_conf = 0.0
    # reuse_origin_ts: timestamp của sample thật (lần gọi API cuối) mà dedup đang kéo theo.
    # Giới hạn MAX_REUSE để không kéo text cũ thành segment quá dài (đứng im nhiều chục giây).
    reuse_origin_ts = None
    max_reuse_seconds = float(os.environ.get("OCR_VISION_MAX_REUSE_SECONDS", "3.0"))
    reasons["dedup_reuse_expired"] = 0
    sig_threshold = float(os.environ.get("OCR_VISION_DEDUP_THRESHOLD", "0.97"))
    processed_frames = 0
    vision_calls = 0
    for index, frame in enumerate(frames):
        # Bounded fast mode: skip theo stride để sample thưa hơn, giảm số vision call.
        if args.frame_stride > 1 and index % args.frame_stride != 0:
            continue
        # Bounded fast mode: giới hạn số frame thật sự được xử lý, không phải index thô.
        if args.max_frames is not None and processed_frames >= args.max_frames:
            reasons["max_frames_stop"] = reasons.get("max_frames_stop", 0) + 1
            break
        # Budget tổng: nếu SIGALRM đang đếm thì thoát sớm, trả partial.
        if _budget_expired():
            reasons["budget_expired"] = reasons.get("budget_expired", 0) + 1
            break
        processed_frames += 1
        ts = args.start + index / args.fps
        sig = _roi_signature(frame, args.roi_top, args.roi_bottom) if dedup else None
        # Dedup: frame kế giống frame trước -> giữ sample cũ, không gọi API.
        # NHƯNG chỉ trong cửa reuse (max_reuse_seconds) để đóng segment khi text/ROI đứng yên quá lâu.
        if dedup and prev_sig is not None and sig is not None and prev_text:
            reuse_expired = reuse_origin_ts is not None and (ts - reuse_origin_ts) > max_reuse_seconds
            if not reuse_expired:
                sim = _signatures_similarity(prev_sig, sig)
                if sim >= sig_threshold:
                    samples.append({"time": ts, "text": prev_text, "confidence": prev_conf, "bbox": None})
                    reasons["dedup_reuse"] = reasons.get("dedup_reuse", 0) + 1
                    continue
            else:
                # Reuse hết hạn: đóng segment (bỏ sample này) để merge tạo gap,
                # buộc gọi API lại ở frame kế nếu subtitle vẫn còn.
                reasons["dedup_reuse_expired"] = reasons.get("dedup_reuse_expired", 0) + 1
                prev_sig = None
                prev_text = None
                reuse_origin_ts = None
        try:
            vision_calls += 1
            text, info = ocr_vision_sample(
                frame, args.roi_top, args.roi_bottom,
                args.prefilter_min_ratio, args.prefilter_min_pixels,
                timeout=vision_timeout,
            )
        except OcrTranscriptTimeout:
            reasons["budget_expired"] = reasons.get("budget_expired", 0) + 1
            break
        if text is None:
            key = info.split(":", 1)[0]
            reasons[key] = reasons.get(key, 0) + 1
            if key == "prefilter_skip":
                skipped += 1
            elif key not in ("no_subtitle", "no_cjk"):
                errors.append({"time": ts, "error": info[:300]})
            prev_sig = sig
            prev_text = None
            reuse_origin_ts = None
            continue
        conf = float(info) if isinstance(info, (int, float)) else 0.6
        if conf < min_min_confidence:
            reasons["low_confidence"] = reasons.get("low_confidence", 0) + 1
            prev_sig = sig
            prev_text = None
            reuse_origin_ts = None
            continue
        samples.append({"time": ts, "text": text, "confidence": conf, "bbox": None})
        prev_sig = sig
        prev_text = text
        prev_conf = conf
        reuse_origin_ts = ts
    reasons["processed_frames"] = processed_frames
    reasons["vision_calls"] = vision_calls
    return samples, errors, skipped, reasons


def _signatures_similarity(a, b):
    """Độ giống của 2 signature (tuple int). 1.0 = giống hệt, 0.0 = khác hoàn toàn."""
    try:
        if not a or not b or len(a) != len(b):
            return 0.0
        if np is not None:
            aa = np.asarray(a, dtype=float)
            bb = np.asarray(b, dtype=float)
            denom = (np.linalg.norm(aa) * np.linalg.norm(bb))
            return float(np.dot(aa, bb) / denom) if denom else 0.0
        n = len(a)
        dot = sum(float(a[i]) * float(b[i]) for i in range(n))
        na = sum(float(x) * float(x) for x in a) ** 0.5
        nb = sum(float(x) * float(x) for x in b) ** 0.5
        return dot / (na * nb) if na and nb else 0.0
    except Exception:
        return 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--output-srt", required=True)
    parser.add_argument("--report-json", required=True)
    parser.add_argument("--fps", type=float, default=float(os.environ.get("SUBTITLE_OCR_TRANSCRIPT_FPS", os.environ.get("SUBTITLE_OCR_FPS", "1"))))
    parser.add_argument("--roi-top", type=float, default=float(os.environ.get("SUBTITLE_DETECT_REGION_TOP_RATIO", "0.58")))
    parser.add_argument("--roi-bottom", type=float, default=float(os.environ.get("SUBTITLE_DETECT_REGION_BOTTOM_RATIO", "1.0")))
    parser.add_argument("--lang", default=os.environ.get("SUBTITLE_OCR_LANG", "ch"))
    parser.add_argument("--min-confidence", type=float, default=float(os.environ.get("SUBTITLE_OCR_MIN_CONFIDENCE", "0.45")))
    parser.add_argument("--merge-gap", type=float, default=float(os.environ.get("OCR_TRANSCRIPT_MERGE_GAP_SEC", "1.2")))
    parser.add_argument("--lead-in", type=float, default=float(os.environ.get("OCR_TRANSCRIPT_LEAD_IN_SEC", "0.08")))
    parser.add_argument("--hold-out", type=float, default=float(os.environ.get("OCR_TRANSCRIPT_HOLD_OUT_SEC", "0.18")))
    parser.add_argument("--start", type=float, default=float(os.environ.get("OCR_TRANSCRIPT_START_SEC", "0")))
    parser.add_argument("--duration", type=float, default=float(os.environ.get("OCR_TRANSCRIPT_DURATION_SEC", "0")))
    parser.add_argument("--prefilter-min-ratio", type=float, default=float(os.environ.get("OCR_TRANSCRIPT_PREFILTER_MIN_RATIO", "0.0012")))
    parser.add_argument("--prefilter-min-pixels", type=int, default=int(os.environ.get("OCR_TRANSCRIPT_PREFILTER_MIN_PIXELS", "80")))
    parser.add_argument("--ocr-engine", default=os.environ.get("SUBTITLE_OCR_ENGINE", "paddleocr"),
                        choices=("paddleocr", "9router_vision"))
    parser.add_argument("--vision-min-confidence", type=float,
                        default=float(os.environ.get("OCR_VISION_MIN_CONFIDENCE", "0.45")))
    # --- Bounded fast mode: giới hạn OCR transcript để không quét mù toàn video tới 900s. ---
    parser.add_argument("--max-frames", type=int, default=int(os.environ.get("OCR_TRANSCRIPT_MAX_FRAMES", "0")),
                        help="Giới hạn số frame được xử lý (0 = không giới hạn).")
    parser.add_argument("--frame-stride", type=int, default=int(os.environ.get("OCR_TRANSCRIPT_FRAME_STRIDE", "1")),
                        help="Chỉ xử lý mỗi frame-thứ-N (1 = mọi frame). VD 3 = sample mỗi 3 frame.")
    parser.add_argument("--vision-timeout", type=float, default=float(os.environ.get("OCR_TRANSCRIPT_VISION_TIMEOUT_SECONDS", "0")),
                        help="Timeout per-call (giây) cho vision API. 0 = dùng default module (60s).")
    parser.add_argument("--total-timeout", type=float, default=float(os.environ.get("OCR_TRANSCRIPT_TOTAL_TIMEOUT_SECONDS", "0")),
                        help="Budget toàn bước OCR (giây, SIGALRM). 0 = không giới hạn nội bộ (dựa shell timeout).")
    parser.add_argument("--disable-paddle-fallback", action="store_true",
                        default=os.environ.get("OCR_TRANSCRIPT_DISABLE_PADDLE_FALLBACK", "0") == "1",
                        help="Bỏ fallback PaddleOCR khi vision không ra sample (tránh init Paddle nặng không cần thiết).")
    args = parser.parse_args()
    # Cho logic so sánh stride/max_frames dễ hơn: normalize 0/1 về no-limit.
    args.frame_stride = max(1, int(args.frame_stride))
    if args.max_frames <= 0:
        args.max_frames = None

    video = Path(args.video)
    output_srt = Path(args.output_srt)
    report_json = Path(args.report_json)

    engine = args.ocr_engine
    # Lazy-load PaddleOCR: chỉ init khi thật sự cần (engine=paddleocr, hoặc fallback enabled).
    # Trước đây init Paddle luôn → chậm + nguy cơ init/fallback làm trễ timeout khi engine=vision.
    disable_fallback = bool(args.disable_paddle_fallback)
    ocr = None
    ocr_kwargs = None
    need_paddle = (engine == "paddleocr") or (engine == "9router_vision" and not disable_fallback)
    if need_paddle:
        try:
            ocr, ocr_kwargs = create_ocr(args.lang)
        except Exception as exc:
            if engine == "paddleocr":
                raise
            # Vision mode: paddle có thể thiếu, ghi nhận để fallback bị skip.
            ocr_kwargs = {"init_error": repr(exc)[:200]}
    else:
        ocr_kwargs = {"skipped": "vision_mode_no_paddle_fallback"}

    samples = []
    errors = []
    skipped_prefilter = 0
    engine_used = engine
    fallback_used = False
    fallback_reason = None
    vision_reasons = {}
    frame_count = 0
    processed_frame_count = 0
    vision_call_count = 0
    timed_out = False
    timeout_reason = ""

    # Budget nội bộ (SIGALRM) — đặt SAU extract_frames để ffmpeg không bị kill giữa chừng.
    try:
        with TemporaryDirectory(prefix="openclaw-ocr-transcript-") as tmp:
            tmp_dir = Path(tmp)
            frames = extract_frames(video, tmp_dir, args.fps, args.start, args.duration)
            frame_count = len(frames)
            # Budget chỉ đếm phần OCR (vision/paddle), không tính ffmpeg extract.
            _start_budget(args.total_timeout)
            if engine == "9router_vision":
                try:
                    samples, errors, skipped_prefilter, vision_reasons = run_vision_on_frames(
                        frames, args, min_min_confidence=args.vision_min_confidence,
                        vision_timeout=(args.vision_timeout or None))
                except OcrTranscriptTimeout:
                    timed_out = True
                    timeout_reason = "vision_budget_exceeded"
                vision_call_count = int((vision_reasons or {}).get("vision_calls", 0))
                processed_frame_count = int((vision_reasons or {}).get("processed_frames", 0))
                # Fallback Paddle khi vision không ra sample hoặc lỗi payload (và chưa bị budget kill).
                if not samples and not timed_out:
                    fallback_reason = "vision_no_samples"
                    if ocr is not None:
                        try:
                            samples, perr, pskip = run_paddle_on_frames(frames, args, ocr)
                            errors.extend(perr)
                            skipped_prefilter = pskip
                            fallback_used = True
                            engine_used = "paddleocr"
                        except OcrTranscriptTimeout:
                            timed_out = True
                            timeout_reason = "paddle_budget_exceeded"
                        except Exception as exc:
                            fallback_reason = f"vision_no_samples_and_paddle_fail:{exc!r}"[:200]
                    elif disable_fallback:
                        fallback_reason = "vision_no_samples_and_paddle_fallback_disabled"
                    else:
                        fallback_reason = "vision_no_samples_and_paddle_unavailable"
                else:
                    engine_used = "9router_vision"
            else:
                if ocr is None:
                    raise RuntimeError("PaddleOCR không khởi động được và engine=paddleocr")
                try:
                    samples, errors, skipped_prefilter = run_paddle_on_frames(frames, args, ocr)
                except OcrTranscriptTimeout:
                    timed_out = True
                    timeout_reason = "paddle_budget_exceeded"
                engine_used = "paddleocr"
                processed_frame_count = len(frames)
    finally:
        _clear_budget()

    segments = merge_samples(samples, args.fps, args.merge_gap, args.lead_in, args.hold_out)
    write_srt(output_srt, segments)
    duration = 0.0
    try:
        duration = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nk=1:nw=1", str(video)], text=True).strip())
    except Exception:
        pass
    coverage = sum(max(0.0, seg["end"] - seg["start"]) for seg in segments) / max(0.001, duration)
    # Quality metrics: phát hiện OCR thưa / cue dài bất thường / dedup reuse kéo text quá lâu.
    ocr_quality_min_text_chars = int(float(os.environ.get("OCR_QUALITY_MIN_TEXT_CHARS", "12")))
    ocr_quality_max_thin_seconds = float(os.environ.get("OCR_QUALITY_MAX_THIN_SECONDS", "6"))
    ocr_quality_max_cue_seconds = float(os.environ.get("OCR_QUALITY_MAX_CUE_SECONDS", "15"))
    ocr_quality_max_reuse_ratio = float(os.environ.get("OCR_QUALITY_MAX_REUSE_RATIO", "0.85"))
    max_cue_seconds = 0.0
    max_text_len = 0
    long_thin_cues = 0
    for seg in segments:
        seg_dur = max(0.0, seg["end"] - seg["start"])
        if seg_dur > max_cue_seconds:
            max_cue_seconds = seg_dur
        seg_text = clean_text(seg.get("text", ""))
        if len(seg_text) > max_text_len:
            max_text_len = len(seg_text)
        if len(seg_text) < ocr_quality_min_text_chars and seg_dur > ocr_quality_max_thin_seconds:
            long_thin_cues += 1
    dedup_reuse = int((vision_reasons or {}).get("dedup_reuse", 0))
    dedup_reuse_ratio = dedup_reuse / max(1, len(samples))
    quality_ok = bool(segments) and max_cue_seconds <= ocr_quality_max_cue_seconds \
        and long_thin_cues == 0 and dedup_reuse_ratio <= ocr_quality_max_reuse_ratio
    # Partial: có samples nhưng bị budget cắt giữa chừng → vẫn dùng được nếu đủ chất lượng.
    partial = bool(timed_out) and bool(samples)
    status = "ok" if not timed_out else ("timeout_partial" if partial else "failed")
    report = {
        "status": status,
        "engine_requested": engine,
        "engine_used": engine_used,
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "vision_reasons": vision_reasons,
        "video": str(video),
        "output_srt": str(output_srt),
        "fps": args.fps,
        "roi_top": args.roi_top,
        "roi_bottom": args.roi_bottom,
        "ocr_kwargs": ocr_kwargs,
        "frame_count": frame_count,
        "processed_frame_count": processed_frame_count,
        "vision_call_count": vision_call_count,
        "sample_count": len(samples),
        "skipped_prefilter": skipped_prefilter,
        "segment_count": len(segments),
        "coverage_ratio": coverage,
        "avg_confidence": sum(seg["confidence"] for seg in segments) / max(1, len(segments)),
        "errors": errors[:20],
        "segments_preview": segments[:20],
        "video_duration": duration,
        "max_cue_seconds": round(max_cue_seconds, 3),
        "max_text_len": max_text_len,
        "long_thin_cues": long_thin_cues,
        "dedup_reuse_ratio": round(dedup_reuse_ratio, 3),
        "quality_ok": quality_ok,
        "partial": partial,
        "timed_out": timed_out,
        "timeout_reason": timeout_reason,
        "bounded_fast_mode": {
            "max_frames": args.max_frames,
            "frame_stride": args.frame_stride,
            "vision_timeout": args.vision_timeout,
            "total_timeout": args.total_timeout,
            "disable_paddle_fallback": disable_fallback,
        },
    }
    report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ocr_transcript_{status} engine={engine_used} segments={len(segments)} coverage={coverage:.3f} quality_ok={quality_ok} partial={partial} timed_out={timed_out} fallback={fallback_used} frames={frame_count}/{processed_frame_count} output={output_srt}", flush=True)


if __name__ == "__main__":
    main()
