#!/usr/bin/env python3
import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
THUMBNAIL_USE_REFERENCE = os.environ.get("THUMBNAIL_USE_REFERENCE", "1") != "0"
THUMBNAIL_TEXT_SAFE_LAYOUT = os.environ.get("THUMBNAIL_TEXT_SAFE_LAYOUT", "1") != "0"
THUMBNAIL_VISION_ENABLED = os.environ.get("THUMBNAIL_VISION_ENABLED", "1") != "0"
FLOW_BRIDGE_ENABLED = os.environ.get("GOOGLE_FLOW_BRIDGE_ENABLED", "1") != "0"
THUMBNAIL_DRY_RUN = os.environ.get("THUMBNAIL_DRY_RUN", "0") != "0"
THUMBNAIL_CREATIVE_ENABLED = os.environ.get("THUMBNAIL_CREATIVE_ENABLED", "1") != "0"
THUMBNAIL_REF_DISCOVER = os.environ.get("THUMBNAIL_REF_DISCOVER", "1") != "0"
THUMBNAIL_QUALITY_GATE_ENABLED = os.environ.get("THUMBNAIL_QUALITY_GATE_ENABLED", "1") != "0"
THUMBNAIL_FLOW_RETRY = int(os.environ.get("THUMBNAIL_FLOW_RETRY", "1"))
# Flow reference upload toggle + report (mới).
FLOW_REFERENCE_UPLOAD = os.environ.get("FLOW_REFERENCE_UPLOAD", "1") != "0"
FLOW_REFERENCE_UPLOAD_REQUIRED = os.environ.get("FLOW_REFERENCE_UPLOAD_REQUIRED", "0") != "0"
# Visual-aware hook refine sau khi có reference (mới).
THUMBNAIL_REFINE_HOOK = os.environ.get("THUMBNAIL_REFINE_HOOK", "1") != "0"

try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
except Exception as exc:
    print(f"ERROR: Python module playwright chưa sẵn sàng: {exc}", file=sys.stderr)
    print("Gợi ý: python3 -m pip install --user --break-system-packages playwright", file=sys.stderr)
    sys.exit(2)

FLOW_URL = os.environ.get("GOOGLE_FLOW_URL", "https://labs.google/fx/tools/flow")
TIMEOUT_SECONDS = int(os.environ.get("GOOGLE_FLOW_THUMBNAIL_TIMEOUT_SECONDS", "900"))
GENERATION_WAIT_SECONDS = int(os.environ.get("GOOGLE_FLOW_GENERATION_WAIT_SECONDS", "720"))
FONT_FILE = os.environ.get("GOOGLE_FLOW_THUMBNAIL_FONT", "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf")
CDP_URLS = [u.strip() for u in os.environ.get(
    "GOOGLE_FLOW_CDP_URLS",
    "http://127.0.0.1:9222,http://172.21.0.1:9223,http://host.docker.internal:9223,http://localhost:9222",
).split(",") if u.strip()]

EDITOR_SELECTOR = ",".join([
    "textarea:not([name*='recaptcha' i]):not([id*='recaptcha' i]):not([class*='recaptcha' i]):not([aria-hidden='true'])",
    "[contenteditable='true']:not([name*='recaptcha' i]):not([id*='recaptcha' i]):not([class*='recaptcha' i]):not([aria-hidden='true'])",
    "[role='textbox']:not([name*='recaptcha' i]):not([id*='recaptcha' i]):not([class*='recaptcha' i]):not([aria-hidden='true'])",
    "input[type='text']:not([name*='recaptcha' i]):not([id*='recaptcha' i]):not([class*='recaptcha' i]):not([aria-hidden='true'])",
])
TEXTAREA_SELECTORS = [EDITOR_SELECTOR]
SUBMIT_SELECTORS = [
    "button:has-text('arrow_forward')",
    "button[aria-disabled='false']:has-text('Tạo')",
    "button:has-text('Create')",
    "button:has-text('Generate')",
    "button:has-text('Submit')",
    "button:has-text('Tạo')",
    "button:has-text('Gửi')",
    "[aria-label*='Create' i]",
    "[aria-label*='Generate' i]",
    "[aria-label*='Submit' i]",
]
PROJECT_SELECTORS = [
    "a[href*='/tools/flow/project/']",
    "a[href*='/fx/vi/tools/flow/project/']",
    "a[href*='/fx/tools/flow/project/']",
    "button:has-text('Get started')",
    "button:has-text('Dự án mới')",
    "button:has-text('New project')",
    "button:has-text('Chỉnh sửa dự án')",
]
DOWNLOAD_SELECTORS = [
    "a[download]",
    "button:has-text('Download')",
    "button:has-text('Tải xuống')",
    "[aria-label*='Download' i]",
    "[aria-label*='Tải' i]",
]
LOGIN_PATTERNS = [
    "sign in",
    "đăng nhập",
    "login",
    "quota",
    "not available",
    "verify",
    "verification",
    "captcha",
    "too many requests",
    "try again later",
    "recaptcha",
    "i'm not a robot",
    "tôi không phải là người máy",
    "unusual traffic",
    "suspicious activity",
]
HARD_BLOCK_PATTERNS = [
    "quota exceeded",
    "usage limit",
    "rate limit",
    "daily limit",
    "generation limit",
    "credit limit",
    "out of credits",
    "not enough credits",
    "not available in your country",
    "you don't have access",
    "too many requests",
    "try again later",
    "recaptcha",
    "unusual traffic",
]


def write_attention_report(output_dir: Path, reason: str, detail: str, page_url: str = "") -> None:
    report = {
        "status": "needs_user_attention",
        "component": "google-flow-thumbnail",
        "reason": reason,
        "detail": detail,
        "page_url": page_url,
        "action_for_user": (
            "Mở Chrome CDP Google Flow, kiểm tra đăng nhập/quota/captcha/limit, "
            "sau đó chạy lại thumbnail-only cho job này nếu muốn ảnh từ Flow."
        ),
        "fallback": "local_reference_thumbnail",
        "created_at": time.strftime("%F %T %z"),
    }
    (output_dir / "thumbnail_flow_status.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "THUMBNAIL_NEEDS_ATTENTION.txt").write_text(
        "Google Flow cần anh Hào can thiệp.\n"
        f"Lý do: {reason}\n"
        f"Chi tiết: {detail}\n"
        "Em đã tạo thumbnail fallback local từ ảnh/video gốc để pipeline không bị kẹt.\n"
        "Nếu muốn thumbnail bằng Flow, mở Chrome CDP xử lý login/quota/captcha/limit rồi chạy lại thumbnail-only.\n",
        encoding="utf-8",
    )

def clear_attention_report(output_dir: Path, page_url: str = "") -> None:
    for name in ("THUMBNAIL_NEEDS_ATTENTION.txt",):
        try:
            (output_dir / name).unlink(missing_ok=True)
        except Exception:
            pass
    report = {
        "status": "done",
        "component": "google-flow-thumbnail",
        "reason": "",
        "detail": "Google Flow đã tạo thumbnail thành công; đã xoá cảnh báo cũ nếu có.",
        "page_url": page_url,
        "fallback": "none",
        "created_at": time.strftime("%F %T %z"),
    }
    (output_dir / "thumbnail_flow_status.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def classify_flow_error(message: str) -> str:
    text = message.lower()
    if "no_visible_non_recaptcha_editor" in text or "không điền được prompt" in text:
        return "flow_ui_changed_or_not_ready"
    if "submit disabled" in text or "vẫn bị disabled" in text:
        return "flow_ui_changed_or_not_ready"
    if "g-recaptcha-response" in text and (
        "not visible" in text
        or "element is not visible" in text
        or "locator.click" in text
        or "timeout" in text
        or "waiting for locator" in text
    ):
        return "flow_ui_changed_or_not_ready"
    if (
        "quota" in text
        or "too many requests" in text
        or "rate limit" in text
        or "usage limit" in text
        or "daily limit" in text
        or "generation limit" in text
        or "credit limit" in text
        or "out of credits" in text
        or "not enough credits" in text
    ):
        return "quota_or_limit"
    if "captcha" in text or "verification" in text or "verify" in text:
        return "captcha_or_verification"
    if "sign in" in text or "login" in text or "đăng nhập" in text:
        return "login_required"
    if "không tìm thấy ô nhập" in text or "đổi ui" in text:
        return "flow_ui_changed_or_not_ready"
    if "cdp" in text:
        return "chrome_cdp_not_ready"
    return "unknown_flow_error"


def log(message: str) -> None:
    stamp = time.strftime("%F %T")
    print(f"[{stamp}] {message}", flush=True)

def write_flow_bridge_status(
    output_dir: Path,
    phase: str,
    status: str,
    detail: str = "",
    progress: int = 0,
    page_url: str = "",
    extra: Optional[dict] = None,
) -> None:
    if not FLOW_BRIDGE_ENABLED:
        return
    payload = {
        "component": "google-flow-thumbnail",
        "bridge_mode": "cdp_safe_bridge",
        "status": status,
        "phase": phase,
        "progress_percent": max(0, min(100, int(progress))),
        "detail": detail,
        "page_url": page_url,
        "last_heartbeat_at": time.strftime("%F %T %z"),
        "recaptcha_policy": "detect_and_ask_user_manual_solve_no_bypass",
    }
    if extra:
        payload.update(extra)
    (output_dir / "thumbnail_flow_bridge_status.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

def write_flow_bridge_request(output_dir: Path, title: str, prompt: str) -> None:
    if not FLOW_BRIDGE_ENABLED:
        return
    reference = output_dir / "thumbnail_reference.jpg"
    request = {
        "component": "google-flow-thumbnail",
        "bridge_mode": "cdp_safe_bridge",
        "created_at": time.strftime("%F %T %z"),
        "output_dir": str(output_dir),
        "title": title,
        "prompt_file": str(output_dir / "thumbnail_prompt.txt"),
        "reference_image": str(reference) if reference.exists() else "",
        "download_target": str(output_dir / "thumbnail_flow_raw.jpg"),
        "final_target": str(output_dir / "thumbnail.jpg"),
        "captcha_policy": "Không tự giải/bypass reCAPTCHA; chỉ phát hiện và yêu cầu anh Hào xử lý trên Chrome thật.",
        "prompt_preview": prompt[:1200],
    }
    (output_dir / "thumbnail_flow_bridge_request.json").write_text(
        json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def read_srt(path: Path, limit: int = 9000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="ignore")
    text = re.sub(r"\d+\s+\d{2}:\d{2}:\d{2},\d{3}\s+-->\s+\d{2}:\d{2}:\d{2},\d{3}", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def choose_title(seed: str) -> str:
    low = seed.lower()
    rules = [
        ("lão tổ", "LÃO TỔ XUẤT QUAN"),
        ("ma vương", "MA VƯƠNG TRỞ LẠI"),
        ("sói", "SÓI TỘC TẤN CÔNG"),
        ("gia tộc", "BIẾN CỐ GIA TỘC"),
        ("báo thù", "TRẢ THÙ ĐẪM MÁU"),
        ("tu tiên", "TU TIÊN ĐẠI CHIẾN"),
        ("bí mật", "BÍ MẬT KINH HOÀNG"),
        ("phản bội", "CÚ PHẢN BỘI"),
    ]
    for needle, title in rules:
        if needle in low:
            return title
    words = re.findall(r"[A-Za-zÀ-ỹ0-9]+", seed)
    if len(words) >= 3:
        candidate = " ".join(words[:5]).upper()
        return candidate[:28]
    return "BIẾN CỐ BẤT NGỜ"


def build_prompt(output_dir: Path) -> tuple[str, str]:
    """Legacy prompt builder; kept only for last-resort fallback."""
    vi = read_srt(output_dir / "vietnamese.srt")
    orig = read_srt(output_dir / "original.srt", 4000)
    source = (output_dir / "source_input.txt").read_text(encoding="utf-8", errors="ignore").strip() if (output_dir / "source_input.txt").exists() else ""
    seed = vi or orig or f"Video source: {source}" or output_dir.name
    title = choose_title(seed)
    reference_note = ""
    reference_meta = output_dir / "thumbnail_reference_meta.json"
    layout_meta = output_dir / "thumbnail_layout.json"
    if reference_meta.exists():
        try:
            meta = json.loads(reference_meta.read_text(encoding="utf-8"))
            source = meta.get("source") or "reference"
            reference_note += f"\nẢnh thumbnail/frame gốc đã được lưu làm reference: thumbnail_reference.jpg (source={source}). Hãy giữ tinh thần, bố cục chính, vị trí nhân vật/chủ thể và màu sắc kịch tính gần reference."
        except Exception:
            pass
    if layout_meta.exists():
        try:
            layout = json.loads(layout_meta.read_text(encoding="utf-8"))
            safe_region = layout.get("safe_text_region") or "top"
            reference_note += f"\nVùng chữ an toàn dự kiến là {safe_region}; vì vậy hãy tránh đặt mặt/đầu nhân vật chính vào vùng chữ này."
        except Exception:
            pass
    vision_prompt = output_dir / "thumbnail_vision_prompt.txt"
    vision_analysis = output_dir / "thumbnail_vision_analysis.json"
    if vision_prompt.exists():
        hint = vision_prompt.read_text(encoding="utf-8", errors="replace").strip()
        if hint:
            reference_note += f"\nPhân tích ảnh reference/vision: {hint[:1200]}"
    elif vision_analysis.exists():
        try:
            analysis = json.loads(vision_analysis.read_text(encoding="utf-8"))
            hint = analysis.get("prompt_hint") or analysis.get("raw_text") or ""
            if hint:
                reference_note += f"\nPhân tích ảnh reference/vision: {str(hint)[:1200]}"
        except Exception:
            pass

    prompt = f"""Tạo một ảnh thumbnail YouTube 16:9, bắt mắt, tương phản mạnh, phù hợp video recap/giải trí tiếng Việt.

Quan trọng: KHÔNG vẽ bất kỳ chữ, tiêu đề, caption, watermark, logo hoặc ký tự nào trong ảnh. Chỉ tạo phần hình nền/nhân vật/chủ thể; chữ tiếng Việt sẽ được chèn bằng công cụ riêng sau.
Hình ảnh phải an toàn, không máu me, không vũ khí chi tiết, không nội dung gây sốc hoặc bạo lực trực diện.

Nội dung video để bám chủ đề: {seed[:2600]}
{reference_note}

Bố cục: nhân vật/chủ thể chính rõ ở tiền cảnh, cảm xúc kịch tính nhưng an toàn, nền điện ảnh, ánh sáng mạnh, màu sắc nổi bật kiểu thumbnail YouTube chuyên nghiệp. Nếu reference có hai nhân vật đối đầu thì giữ cảm giác trái/phải đối đầu; nếu reference có nhân vật lớn một bên thì giữ chủ thể lớn ở bên đó. Nếu nội dung là hoạt hình/truyện Trung Quốc/tu tiên thì dùng phong cách cinematic anime fantasy; nếu nội dung đời thực thì dùng phong cách cinematic realistic. Xuất ra phần hình nền/nhân vật sạch, không chữ.""".strip()
    return title, prompt


def prepare_creative(output_dir: Path, debug_dir: Path) -> dict:
    """Run thumbnail_creative.py -> story analysis + selected hook. Fail-open.

    The creative module writes thumbnail_story_analysis.json and
    thumbnail_hook_selected.json directly to output_dir; we read those as the
    source of truth (its stdout may contain interleaved log lines).
    """
    if not THUMBNAIL_CREATIVE_ENABLED:
        log("Creative module disabled (THUMBNAIL_CREATIVE_ENABLED=0); fallback heuristic title.")
        return {"hook": "", "selected_angle": "", "fallback_reason": "creative_disabled"}
    code, out = run_helper("thumbnail_creative.py", str(output_dir))
    (debug_dir / "thumbnail_creative.log").write_text(out, encoding="utf-8", errors="replace")
    if code != 0:
        log(f"WARN: thumbnail_creative.py exit={code}; fallback heuristic. {out[-300:]}")
        return {"hook": "", "selected_angle": "", "fallback_reason": f"creative_exit_{code}"}

    story = {}
    story_path = output_dir / "thumbnail_story_analysis.json"
    if story_path.exists():
        try:
            story = json.loads(story_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    selected = {}
    sel_path = output_dir / "thumbnail_hook_selected.json"
    if sel_path.exists():
        try:
            selected = json.loads(sel_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    hook = (selected.get("hook") or "").strip()
    angle = (selected.get("selected_angle") or "").strip()
    fallback_reason = story.get("fallback_reason") if story.get("status") != "ok" else None
    if not hook:
        log("WARN: creative module did not return a hook; fallback heuristic title.")
        return {"hook": "", "selected_angle": angle,
                "fallback_reason": fallback_reason or "no_hook"}
    log(f"Creative hook: {hook} (angle={angle}) fallback={fallback_reason or 'none'}")
    return {"hook": hook, "selected_angle": angle,
            "fallback_reason": fallback_reason, "story_analysis": story}


def discover_references(output_dir: Path, angle: str, hook: str, debug_dir: Path) -> dict:
    """Run thumbnail_reference.py in discover mode -> hero + support refs + legacy reference."""
    if not THUMBNAIL_USE_REFERENCE or not THUMBNAIL_REF_DISCOVER:
        # Legacy single-frame path.
        code, out = run_helper("thumbnail_reference.py", str(output_dir), "--mode", "legacy")
        (debug_dir / "thumbnail_reference.log").write_text(out, encoding="utf-8", errors="replace")
        return {"hero_reference": str(output_dir / "thumbnail_reference.jpg"), "legacy": True}
    code, out = run_helper("thumbnail_reference.py", str(output_dir), "--mode", "discover",
                           "--angle", angle or "", "--hook", hook or "")
    (debug_dir / "thumbnail_reference.log").write_text(out, encoding="utf-8", errors="replace")
    sel = _parse_last_json_object(out)
    # Khôi phục từ artifact khi stdout parse fail (helper in JSON pretty multi-line).
    if not sel and (output_dir / "thumbnail_character_selected.json").exists():
        try:
            sel = json.loads((output_dir / "thumbnail_character_selected.json").read_text(encoding="utf-8"))
            log("discover_references: stdout parse fail, dùng thumbnail_character_selected.json.")
        except Exception:
            pass
    if code != 0 or not sel.get("hero_reference"):
        log(f"WARN: reference discovery failed; legacy fallback. {out[-300:]}")
        # Try legacy path so thumbnail_reference.jpg exists.
        run_helper("thumbnail_reference.py", str(output_dir), "--mode", "legacy")
        sel = {"hero_reference": str(output_dir / "thumbnail_reference.jpg"), "fallback_reason": "discover_failed"}
    # Also run layout analysis on the hero so text-plan can use it.
    layout = output_dir / "thumbnail_layout.json"
    reference = Path(sel.get("hero_reference") or (output_dir / "thumbnail_reference.jpg"))
    if reference.exists():
        c2, o2 = run_helper("thumbnail_layout.py", str(reference), str(layout))
        (debug_dir / "thumbnail_layout.log").write_text(o2, encoding="utf-8", errors="replace")
        if c2 == 0 and THUMBNAIL_VISION_ENABLED:
            analysis = output_dir / "thumbnail_vision_analysis.json"
            prompt = output_dir / "thumbnail_vision_prompt.txt"
            c3, o3 = run_helper("thumbnail_vision.py", str(reference), str(analysis), str(prompt))
            (debug_dir / "thumbnail_vision.log").write_text(o3, encoding="utf-8", errors="replace")
            # Alias reference_visual_analysis.json để gate/plan/creative đọc tên thống nhất.
            if analysis.exists():
                try:
                    shutil.copyfile(analysis, output_dir / "reference_visual_analysis.json")
                except Exception:
                    pass
    return sel


def _safe_text_region(output_dir: Path) -> str:
    """Pick a text anchor that avoids the subject, using layout + vision analysis."""
    layout_path = output_dir / "thumbnail_layout.json"
    region = "top"
    if layout_path.exists():
        try:
            layout = json.loads(layout_path.read_text(encoding="utf-8"))
            region = layout.get("safe_text_region") or "top"
        except Exception:
            pass
    # Vision analysis avoid_text_regions can override.
    analysis_path = output_dir / "thumbnail_vision_analysis.json"
    if analysis_path.exists():
        try:
            analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
            avoid = analysis.get("avoid_text_regions") or []
            if region in avoid:
                # flip to the opposite side.
                region = {"top": "bottom", "bottom": "top",
                          "top_left": "bottom_right", "top_right": "bottom_left",
                          "bottom_left": "top_right", "bottom_right": "top_left"}.get(region, "bottom")
        except Exception:
            pass
    return region


ANCHOR_BOX = {
    "top": [0.0, 0.0, 1.0, 0.22],
    "bottom": [0.0, 0.76, 1.0, 1.0],
    "bottom_left": [0.0, 0.64, 0.56, 1.0],
    "bottom_right": [0.44, 0.64, 1.0, 1.0],
    "top_left": [0.0, 0.0, 0.58, 0.26],
    "top_right": [0.42, 0.0, 1.0, 0.26],
}


def build_text_plan(output_dir: Path, hook: str) -> dict:
    """Choose line breaks + text box + style for local Vietnamese text composition."""
    plan_path = output_dir / "thumbnail_text_plan.json"
    anchor = _safe_text_region(output_dir)
    text_box = ANCHOR_BOX.get(anchor, ANCHOR_BOX["top"])
    words = hook.split()
    # Decide line breaks: 1 line if short, else 2 balanced lines.
    if len(words) <= 2 or len(hook) <= 18:
        line_breaks = [hook]
    else:
        mid = max(1, len(words) // 2)
        # Try to keep emphasis word at end of first line for impact.
        line_breaks = [" ".join(words[:mid]), " ".join(words[mid:])]
        if len(line_breaks[1]) > len(line_breaks[0]) + 6:
            mid += 1
            line_breaks = [" ".join(words[:mid]), " ".join(words[mid:])]
    # Emphasis word = longest token.
    emphasis_word = max(words, key=len) if words else ""
    plan = {
        "selected_hook": hook,
        "line_breaks": line_breaks[:2],
        "anchor": anchor,
        "text_box": text_box,
        "font_preset": "bold_caps",
        "fill": "#FFDE46",
        "stroke": "#000000",
        "stroke_width": 6,
        "shadow": True,
        "background_panel": {"enabled": True, "alpha": 165},
        "emphasis_word": emphasis_word,
        "emphasis_scale": 1.25,
    }
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan


def build_image_plan_and_prompt(output_dir: Path, creative: dict, reference: dict) -> tuple[str, str, dict]:
    """Produce thumbnail_image_plan.json + thumbnail_image_prompt.json + thumbnail_prompt.txt."""
    story_path = output_dir / "thumbnail_story_analysis.json"
    story = {}
    if story_path.exists():
        try:
            story = json.loads(story_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    hook = creative.get("hook") or ""
    angle = creative.get("selected_angle") or "khoảnh khắc kịch tính"
    hero_ref = reference.get("hero_reference") or ""
    generation_mode = "reference_prompt_only"  # may be upgraded to reference_upload at Flow time

    text_plan_path = output_dir / "thumbnail_text_plan.json"
    text_plan = {}
    if text_plan_path.exists():
        try:
            text_plan = json.loads(text_plan_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    negative_space_for_text = text_plan.get("anchor") or _safe_text_region(output_dir)

    plan = {
        "selected_hook": hook,
        "selected_angle": angle,
        "main_subject": story.get("main_character") or "nhân vật chính kịch tính",
        "expression": story.get("strongest_emotion") or "kịch tính, căng thẳng",
        "background": "cinematic, high contrast, saturated colors, phù hợp thumbnail YouTube",
        "composition": "chủ thể chính rõ ở tiền cảnh, nền điện ảnh, ánh sáng mạnh",
        "negative_space_for_text": negative_space_for_text,
        "style": "cinematic anime fantasy" if any(k in (story.get("core_plot") or "").lower()
                  for k in ("tu tiên", "lão tổ", "ma vương", "sói", "tu linh", "linh khí"))
                  else "cinematic realistic",
        "negative_prompt": "no text, no title, no caption, no watermark, no logo, no Chinese characters, "
                            "no subtitles, no signature, no frame, safe for work, no graphic violence",
        "generation_mode": generation_mode,
        "reference_image": hero_ref,
        "story": story,
    }
    (output_dir / "thumbnail_image_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    # Build the actual Flow prompt text (two variants: upload + text-only).
    vision_hint = ""
    vp = output_dir / "thumbnail_vision_prompt.txt"
    if vp.exists():
        vision_hint = vp.read_text(encoding="utf-8", errors="replace").strip()
    has_ref = bool(hero_ref and Path(hero_ref).exists())
    prompt_upload, prompt_text_only = _build_flow_prompt_variants(
        hook, angle, story, plan, negative_space_for_text, vision_hint, hero_ref, has_ref)

    # Mặc định prompt_text = text-only (an toàn: không giả vờ có ảnh đính kèm).
    # Sau khi biết gen_mode thật (upload vs text-only) ở generate_via_flow/dry-run,
    # caller cập nhật thumbnail_prompt.txt + image_prompt.prompt_text = variant đã dùng.
    prompt = prompt_text_only
    image_prompt_obj = {
        "selected_hook": hook,
        "selected_angle": angle,
        "prompt_text": prompt,
        "prompt_upload": prompt_upload,
        "prompt_text_only": prompt_text_only,
        "negative_prompt": plan["negative_prompt"],
        "generation_mode": generation_mode,
        "reference_image": hero_ref,
        "style": plan["style"],
    }
    (output_dir / "thumbnail_image_prompt.json").write_text(
        json.dumps(image_prompt_obj, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "thumbnail_prompt.txt").write_text(prompt + "\n", encoding="utf-8")
    return hook, prompt, plan


def _build_flow_prompt_variants(hook: str, angle: str, story: dict, plan: dict,
                                 negative_space_for_text: str, vision_hint: str,
                                 hero_ref: str, has_ref: bool) -> tuple[str, str]:
    """Sinh 2 variant prompt: (prompt_upload, prompt_text_only).

    prompt_upload: được phép nói rõ "use the attached reference image" (khi upload dùng được).
    prompt_text_only: chỉ mô tả reference bằng text, KHÔNG giả vờ có ảnh đính kèm.
    """
    story_seed = (story.get("core_plot") or "") + " | " + (story.get("main_conflict") or "")
    vision_line = (f"Phân tích reference/vision: {vision_hint[:900]}") if vision_hint else ""
    common = f"""Tạo một ảnh thumbnail YouTube 16:9, bắt mắt, tương phản mạnh, phù hợp video recap/giải trí tiếng Việt.

QUAN TRỌNG: KHÔNG vẽ bất kỳ chữ, tiêu đề, caption, watermark, logo, ký tự hoặc phụ đề nào (kể cả tiếng Trung). Chỉ tạo phần hình nền/nhân vật/chủ thể; chữ tiếng Việt sẽ được chèn bằng công cụ riêng sau.
Ảnh phải an toàn: không máu me, không vũ khí chi tiết, không nội dung gây sốc hoặc bạo lực trực diện.

Chủ đề/angle: {angle}
Hook đã chọn (chỉ tham khảo chủ đề, KHÔNG vẽ chữ này): {hook}
Nội dung: {story_seed[:1800]}"""

    ref_note_upload = ""
    ref_note_text = ""
    if has_ref:
        ref_note_upload = (
            "\nẢnh reference đã ĐÍNH KÈM (attached): dùng ảnh đính kèm làm chuẩn — giữ tinh thần, bố cục chính, "
            "vị trí nhân vật/chủ thể và màu sắc kịch tính gần ảnh reference. Nếu reference có hai nhân vật đối đầu "
            "thì giữ cảm giác trái/phải đối đầu; nếu có nhân vật lớn một bên thì giữ chủ thể lớn ở bên đó."
        )
        ref_note_text = (
            "\nCó một ảnh reference chuẩn (không đính kèm, chỉ mô tả): giữ tinh thần, bố cục chính, "
            "vị trí nhân vật/chủ thể và màu sắc kịch tính theo mô tả trên. KHÔNG yêu cầu đính kèm ảnh; "
            "chỉ mô tả bằng text ở đây. Ảnh reference: " + str(hero_ref)
        )

    tail = f"""
{vision_line}

Bố cục: chủ thể chính "{plan['main_subject']}" rõ ở tiền cảnh, biểu cảm "{plan['expression']}", phong cách {plan['style']}.
Yêu cầu negative space: chừa vùng trống ở phía "{negative_space_for_text}" để chèn chữ local sau, KHÔNG đặt mặt/đầu nhân vật vào vùng đó.
Negative prompt: {plan['negative_prompt']}.
Xuất ra phần hình nền/nhân vật sạch, không chữ.""".strip()

    def _join(*parts: str) -> str:
        return "\n".join(p for p in parts if p).strip()

    prompt_upload = _join(common, ref_note_upload, tail)
    prompt_text_only = _join(common, ref_note_text, tail)
    return prompt_upload, prompt_text_only


def compose_vietnamese_text(thumbnail: Path, hook: str, output_dir: Path, debug_dir: Path) -> bool:
    """Build text plan (if missing) and overlay Vietnamese text locally via composer."""
    plan_path = output_dir / "thumbnail_text_plan.json"
    if not plan_path.exists():
        build_text_plan(output_dir, hook)
    layout_arg = str(plan_path) if plan_path.exists() else str(output_dir / "thumbnail_layout.json")
    code, out = run_helper("thumbnail_composer.py", str(thumbnail), hook, layout_arg, str(thumbnail), str(debug_dir))
    (debug_dir / "thumbnail_safe_text.log").write_text(out, encoding="utf-8", errors="replace")
    return code == 0


def _compose_force_large(thumbnail: Path, hook: str, output_dir: Path, debug_dir: Path) -> None:
    """Re-compose chữ với force-large settings (font lớn + stroke dày) trên ảnh Flow gốc.

    Dùng thumbnail_flow_raw.jpg (ảnh Flow chưa chèn chữ) làm base, ép font/stroke lớn qua
    text_plan override, ghi đè thumbnail.jpg. Rẻ hơn regenerate Flow.
    """
    raw = output_dir / "thumbnail_flow_raw.jpg"
    base = raw if raw.exists() else thumbnail
    # Override text_plan: force stroke_width lớn + style pro_youtube.
    plan_path = output_dir / "thumbnail_text_plan.json"
    plan = _load_json(plan_path) or {}
    plan["stroke_width"] = max(8, int(plan.get("stroke_width", 6)) + 4)
    plan["style"] = "pro_youtube"
    plan["emphasis_scale"] = 1.35
    force_plan = output_dir / "thumbnail_text_plan_force.json"
    force_plan.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    code, out = run_helper("thumbnail_composer.py", str(base), hook, str(force_plan), str(thumbnail), str(debug_dir))
    (debug_dir / "thumbnail_safe_text_force.log").write_text(out, encoding="utf-8", errors="replace")

def run_helper(script_name: str, *args: str) -> tuple[int, str]:
    script = SCRIPT_DIR / script_name
    proc = subprocess.run([sys.executable, str(script), *map(str, args)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return proc.returncode, proc.stdout

def shell_quote_ffmpeg_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")

def overlay_vietnamese_title(image_path: Path, title: str, debug_dir: Path) -> None:
    """Legacy overlay kept for last-resort fallback path."""
    plan_path = image_path.parent / "thumbnail_text_plan.json"
    layout = image_path.parent / "thumbnail_layout.json"
    arg_path = str(plan_path) if plan_path.exists() else str(layout)
    if THUMBNAIL_TEXT_SAFE_LAYOUT and Path(arg_path).exists():
        code, out = run_helper("thumbnail_composer.py", str(image_path), title, arg_path, str(image_path), str(debug_dir))
        if code == 0:
            (debug_dir / "thumbnail_safe_text.log").write_text(out, encoding="utf-8", errors="replace")
            return
        log(f"WARN: safe text composer lỗi; fallback overlay cũ. Chi tiết: {out[-300:]}")
    font = Path(FONT_FILE)
    if not font.exists():
        raise RuntimeError(f"Không thấy font chữ Việt: {font}")
    temp = image_path.with_suffix(".title.tmp.jpg")
    text = shell_quote_ffmpeg_text(title)
    vf = (
        "scale=1280:720:force_original_aspect_ratio=increase,"
        "crop=1280:720,"
        "drawbox=x=0:y=0:w=iw:h=150:color=black@0.58:t=fill,"
        f"drawtext=fontfile='{font}':text='{text}':"
        "x=(w-text_w)/2:y=32:fontsize=74:fontcolor=#FFD84D:"
        "borderw=6:bordercolor=black:shadowx=4:shadowy=4:shadowcolor=black"
    )
    subprocess.run([
        "ffmpeg", "-y", "-i", str(image_path), "-vf", vf,
        "-frames:v", "1", "-q:v", "2", str(temp),
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    shutil.copyfile(image_path, debug_dir / "thumbnail_flow_raw.jpg")
    temp.replace(image_path)


async def upload_reference_to_flow(page, hero_reference: Path, debug_dir: Path) -> str:
    """Attempt to upload a reference image to Google Flow's composer. Non-fatal.

    Returns 'reference_upload' if a file input was found and used, else
    'reference_prompt_only'. Never raises. Honors FLOW_REFERENCE_UPLOAD env
    (0 -> skip upload, luôn prompt_only) và ghi flow_upload_status.json.
    """
    if not FLOW_REFERENCE_UPLOAD:
        log("FLOW_REFERENCE_UPLOAD=0: skip upload, dùng reference_prompt_only.")
        (debug_dir / "flow_upload_status.json").write_text(json.dumps(
            {"requested": False, "used": False, "status": "disabled_by_env",
             "mode": "reference_prompt_only"}, ensure_ascii=False, indent=2), encoding="utf-8")
        return "reference_prompt_only"
    if not hero_reference or not Path(hero_reference).exists():
        (debug_dir / "flow_upload_status.json").write_text(json.dumps(
            {"requested": True, "used": False, "status": "no_hero_reference",
             "mode": "reference_prompt_only"}, ensure_ascii=False, indent=2), encoding="utf-8")
        return "reference_prompt_only"
    requested = True
    try:
        locator_info = await page.evaluate("""
        () => {
          function visible(el) {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 12 && r.height > 12 && s.visibility !== 'hidden' &&
              s.display !== 'none' && Number(s.opacity || 1) > 0.05;
          }
          const fileInput = Array.from(document.querySelectorAll('input[type="file"]')).find(visible);
          const attachBtns = Array.from(document.querySelectorAll('button,[role="button"],[aria-label]'))
            .filter(visible)
            .filter(el => /upload|attach|reference|image|tải ảnh|đính kèm|tham chiếu|ảnh/i.test(
              `${el.innerText || ''} ${el.getAttribute('aria-label') || ''} ${el.title || ''}`))
            .map(el => ({tag: el.tagName.toLowerCase(), aria: el.getAttribute('aria-label') || '', text: (el.innerText||'').slice(0,40)}));
          return {
            hasFileInput: !!fileInput,
            fileInputVisible: !!fileInput,
            attachButtons: attachBtns.slice(0, 6),
          };
        }
        """)
        (debug_dir / "flow_upload_candidates.json").write_text(
            json.dumps(locator_info, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        log(f"WARN: upload_reference probe failed: {exc}")
        (debug_dir / "flow_upload_status.json").write_text(json.dumps(
            {"requested": requested, "used": False, "status": f"probe_failed: {exc}",
             "mode": "reference_prompt_only"}, ensure_ascii=False, indent=2), encoding="utf-8")
        return "reference_prompt_only"

    if not locator_info or not locator_info.get("hasFileInput"):
        log("Flow upload UI not found; using reference_prompt_only (prompt carries reference description).")
        (debug_dir / "flow_upload_status.json").write_text(json.dumps(
            {"requested": requested, "used": False, "status": "no_file_input",
             "mode": "reference_prompt_only"}, ensure_ascii=False, indent=2), encoding="utf-8")
        return "reference_prompt_only"

    try:
        file_input = page.locator('input[type="file"]').first
        await file_input.set_input_files(str(hero_reference))
        # Some Flow UIs need an attach button click after choosing the file.
        for sel in ["button:has-text('Upload')", "button:has-text('Tải ảnh')", "[aria-label*='Upload' i]"]:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=500):
                    await btn.click(timeout=2000)
                    break
            except Exception:
                continue
        log(f"Reference uploaded to Flow: {hero_reference}")
        (debug_dir / "flow_upload_status.json").write_text(json.dumps(
            {"requested": requested, "used": True, "status": "uploaded",
             "mode": "reference_upload", "hero_reference": str(hero_reference)},
            ensure_ascii=False, indent=2), encoding="utf-8")
        return "reference_upload"
    except Exception as exc:  # noqa: BLE001
        log(f"WARN: reference upload failed; fallback reference_prompt_only. {exc}")
        (debug_dir / "flow_upload_status.json").write_text(json.dumps(
            {"requested": requested, "used": False, "status": f"upload_failed: {exc}",
             "mode": "reference_prompt_only"}, ensure_ascii=False, indent=2), encoding="utf-8")
        return "reference_prompt_only"


def _parse_last_json_object(stdout: str) -> dict:
    """Parse JSON object cuối cùng từ stdout helper (có thể kèm log + JSON pretty multi-line).

    thumbnail_reference.py in `json.dumps(meta, indent=2)` -> nhiều dòng. Dùng JSONDecoder
    quét từ trái qua phải, giữ object cuối cùng parse được (chấp nhận log lẫn trong output).
    Trả {} nếu không tìm thấy JSON object nào.
    """
    if not stdout:
        return {}
    decoder = json.JSONDecoder()
    text = stdout
    last_obj: dict = {}
    idx = 0
    while idx < len(text):
        brace = text.find("{", idx)
        if brace == -1:
            break
        try:
            obj, end = decoder.raw_decode(text[brace:])
            if isinstance(obj, dict):
                last_obj = obj
            idx = brace + end
        except json.JSONDecodeError:
            idx = brace + 1
    return last_obj


def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _write_debug_grid(output_dir: Path, thumbnail: Path) -> None:
    """Ghép original Flow + text preview + final + mask thành thumbnail_debug_grid.jpg."""
    try:
        from PIL import Image as _Image
        cells = []
        raw = output_dir / "thumbnail_flow_raw.jpg"
        preview = output_dir / "thumbnail_text_preview.jpg"
        mask = output_dir / "google_flow_debug" / "thumbnail_text_mask_debug.png"
        final = thumbnail if thumbnail.exists() else None
        for p in (raw, preview, final):
            if p and Path(p).exists():
                cells.append(_Image.open(Path(p)).convert("RGB").resize((480, 270)))
        if mask.exists():
            cells.append(_Image.open(mask).convert("RGB").resize((480, 270)))
        if len(cells) < 2:
            return
        cols = 2
        rows = (len(cells) + cols - 1) // cols
        grid = _Image.new("RGB", (cols * 480, rows * 270), (20, 20, 20))
        for i, c in enumerate(cells):
            grid.paste(c, ((i % cols) * 480, (i // cols) * 270))
        grid.save(output_dir / "thumbnail_debug_grid.jpg", "JPEG", quality=88)
    except Exception as exc:
        log(f"WARN: debug grid failed: {exc}")


def quality_gate(output_dir: Path, thumbnail: Path, hook: str, reference: dict) -> dict:
    """Quality gate v2: đọc composer/reference/upload report, check text thật, smart retry.

    returns report dict có thêm 'retry_action' ('composer_reroll' | 'flow_regen' | 'none')
    để caller quyết định retry rẻ (composer) vs đắt (Flow regen).
    """
    report_path = output_dir / "thumbnail_quality_report.json"
    composer = _load_json(output_dir / "thumbnail_composer_report.json")
    ref_report = _load_json(output_dir / "reference_selection_report.json")
    upload = _load_json(output_dir / "prompt_with_reference.json")

    scores = {
        "main_character_visibility": 6.0,
        "hook_readability_mobile": 6.0,
        "text_image_alignment": 6.0,
        "hook_specificity": 6.0,
        "character_relevance": 6.0,
        "visual_clickability": 6.0,
        "clutter_score": 6.0,
        "text_size": 6.0,
        "text_stroke": 6.0,
        "panel_coverage": 8.0,
    }
    notes = []
    retry_action = "none"

    # Hook length (chars + words) thay vì chỉ words.
    hw = len(hook.split())
    hc = len(hook)
    if hw <= 3 and hc <= 24:
        scores["hook_readability_mobile"] = 9.0
    elif hw <= 5 and hc <= 36:
        scores["hook_readability_mobile"] = 7.0
    else:
        scores["hook_readability_mobile"] = 4.0
        notes.append(f"Hook dài ({hw} từ, {hc} ký tự), khó đọc trên mobile.")

    # Hook specificity từ reference fallback / refine.
    creative_fb = reference.get("fallback_reason") if isinstance(reference, dict) else ""
    if not creative_fb:
        scores["hook_specificity"] = 7.5
    else:
        scores["hook_specificity"] = 5.0
        notes.append(f"Hook có thể generic do creative fallback: {creative_fb}")

    # Reference: hero + source + score thật.
    if isinstance(reference, dict) and reference.get("hero_reference") and Path(reference["hero_reference"]).exists():
        scores["character_relevance"] = 7.0
        scores["main_character_visibility"] = 7.0
        src = ref_report.get("winner_source") if ref_report else reference.get("source", "")
        if src in ("bilibili_cover", "provided_reference"):
            notes.append(f"Reference = {src} (cover/provided làm candidate).")
    else:
        scores["character_relevance"] = 3.0
        scores["main_character_visibility"] = 3.0
        notes.append("Không có reference nhân vật rõ.")

    # Composer report: text size + stroke + panel thật.
    font_size = int(composer.get("font_size") or 0)
    stroke_w = int(composer.get("stroke_width") or 0)
    panel_used = bool(composer.get("background_panel"))
    canvas_w = 1280
    if font_size:
        # Text size: font >= 48 tốt cho 1280 canvas; <40太小.
        if font_size >= 56:
            scores["text_size"] = 9.0
        elif font_size >= 48:
            scores["text_size"] = 7.5
        elif font_size >= 40:
            scores["text_size"] = 5.5
            notes.append(f"Font size nhỏ ({font_size}px), khó đọc mobile.")
            retry_action = "composer_reroll"
        else:
            scores["text_size"] = 3.0
            notes.append(f"Font size quá nhỏ ({font_size}px).")
            retry_action = "composer_reroll"
    # Stroke tỉ lệ: stroke_width / font_size nên >= 0.06.
    if font_size and stroke_w:
        ratio = stroke_w / font_size
        if ratio >= 0.08:
            scores["text_stroke"] = 8.5
        elif ratio >= 0.06:
            scores["text_stroke"] = 7.0
        else:
            scores["text_stroke"] = 4.5
            notes.append(f"Stroke mỏng ({stroke_w}/{font_size}={ratio:.2f}), kém nổi.")
            if retry_action == "none":
                retry_action = "composer_reroll"
    # Panel coverage: panel lớn = xấu.
    tb = composer.get("text_box") or []
    if panel_used and len(tb) == 4:
        coverage = ((tb[2] - tb[0]) * (tb[3] - tb[1])) / (canvas_w * 720)
        if coverage > 0.35:
            scores["panel_coverage"] = 4.0
            notes.append(f"Panel đen quá lớn ({coverage*100:.0f}% canvas).")
            if retry_action == "none":
                retry_action = "composer_reroll"
        elif coverage > 0.22:
            scores["panel_coverage"] = 6.5
        else:
            scores["panel_coverage"] = 8.5

    # Upload status (informational, không trừ điểm).
    if upload:
        if upload.get("upload_used"):
            notes.append("Flow reference upload: used.")
        elif upload.get("upload_requested"):
            notes.append(f"Flow reference upload: requested nhưng {upload.get('upload_status','')}; dùng prompt text-only.")

    # Visual CV (giữ logic cũ).
    try:
        from PIL import Image, ImageStat, ImageFilter
        img = Image.open(thumbnail).convert("RGB").resize((640, 360))
        gray = img.convert("L")
        edges = gray.filter(ImageFilter.FIND_EDGES)
        edge_mean = ImageStat.Stat(edges).mean[0]
        contrast = ImageStat.Stat(gray).stddev[0]
        if edge_mean > 35:
            scores["clutter_score"] = 4.0
            notes.append(f"Ảnh nhiều chi tiết/edge (edge_mean={edge_mean:.1f}), có thể rối.")
            if retry_action == "none":
                retry_action = "flow_regen"
        elif edge_mean < 8:
            scores["clutter_score"] = 9.0
        else:
            scores["clutter_score"] = 7.0
        if contrast < 35:
            scores["visual_clickability"] = 4.0
            notes.append("Tương phản thấp.")
            if retry_action == "none":
                retry_action = "flow_regen"
        else:
            scores["visual_clickability"] = 7.5
    except Exception as exc:  # noqa: BLE001
        notes.append(f"quality_gate CV analysis skipped: {exc}")

    overall = sum(scores.values()) / len(scores)
    if any(v < 4.0 for v in scores.values()):
        status = "needs_attention"
    elif overall >= 7.0:
        status = "pass"
    elif overall >= 5.5:
        status = "warning"
    else:
        status = "failed_fallback_used"

    report = {
        "component": "google-flow-thumbnail",
        "hook": hook,
        "scores": {k: round(v, 2) for k, v in scores.items()},
        "overall": round(overall, 2),
        "status": status,
        "retry_action": retry_action,
        "notes": notes,
        "thumbnail": str(thumbnail) if thumbnail.exists() else "",
        "composer_report": str(output_dir / "thumbnail_composer_report.json"),
        "reference_report": str(output_dir / "reference_selection_report.json"),
        "upload_report": str(output_dir / "prompt_with_reference.json"),
        "created_at": time.strftime("%F %T %z"),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if status in ("needs_attention", "warning"):
        _write_debug_grid(output_dir, thumbnail)
    return report


def ensure_jpeg(src: Path, dst: Path) -> None:
    if src == dst and dst.exists():
        return
    tmp = dst.with_suffix(dst.suffix + ".tmp.jpg")
    try:
        subprocess.run(["ffmpeg", "-y", "-i", str(src), "-frames:v", "1", "-q:v", "2", str(tmp)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        tmp.replace(dst)
    except Exception:
        if src != dst:
            shutil.copyfile(src, dst)


def create_local_fallback_thumbnail(output_dir: Path, thumbnail: Path, title: str, debug_dir: Path, reason: str) -> bool:
    sources = [
        output_dir / "thumbnail_flow_raw.jpg",
        output_dir / "thumbnail_reference.jpg",
        output_dir / "input.mp4",
    ]
    temp = output_dir / "thumbnail_fallback_base.jpg"
    for source in sources:
        if not source.exists() or source.stat().st_size <= 0:
            continue
        try:
            if source.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}:
                subprocess.run([
                    "ffmpeg", "-y", "-ss", "3", "-i", str(source),
                    "-frames:v", "1", "-q:v", "2", str(temp),
                ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            else:
                ensure_jpeg(source, temp)
            if temp.exists() and temp.stat().st_size > 0:
                ensure_jpeg(temp, thumbnail)
                overlay_vietnamese_title(thumbnail, title, debug_dir)
                (debug_dir / "thumbnail_fallback_reason.txt").write_text(reason + "\n", encoding="utf-8")
                log(f"WARN_USER_ACTION_REQUIRED: Google Flow lỗi ({reason}); đã tạo thumbnail fallback local: {thumbnail}")
                return thumbnail.exists() and thumbnail.stat().st_size > 0
        except Exception as exc:
            log(f"WARN: fallback thumbnail từ {source} lỗi: {exc}")
    return False


async def connect_browser(playwright):
    errors = []
    for cdp_url in CDP_URLS:
        try:
            browser = await playwright.chromium.connect_over_cdp(cdp_url, timeout=8000)
            log(f"Connected CDP: {cdp_url}")
            return browser, cdp_url
        except Exception as exc:
            errors.append(f"{cdp_url}: {exc}")
    raise RuntimeError("Không kết nối được Chrome CDP. " + " | ".join(errors))


async def first_visible(page, selectors, timeout=3000):
    for selector in selectors:
        try:
            loc = page.locator(selector).first
            await loc.wait_for(state="visible", timeout=timeout)
            return loc, selector
        except Exception:
            continue
    return None, None

async def has_prompt_editor(page) -> bool:
    try:
        return bool(await page.evaluate("""
        () => {
          function visible(el) {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 20 && r.height > 12 && s.visibility !== 'hidden' &&
              s.display !== 'none' && Number(s.opacity || 1) > 0.05;
          }
          return Array.from(document.querySelectorAll("textarea,[contenteditable='true'],[role='textbox'],input[type='text']"))
            .some(el => {
              const r = el.getBoundingClientRect();
              const label = `${el.getAttribute('aria-label') || ''} ${el.getAttribute('placeholder') || ''} ${el.innerText || el.value || ''}`.toLowerCase();
              const attrs = `${el.id || ''} ${el.name || ''} ${el.className || ''}`;
              if (/recaptcha|g-recaptcha|hcaptcha/i.test(attrs)) return false;
              const tag = el.tagName.toLowerCase();
              const promptLike = label.includes('bạn muốn tạo gì') || label.includes('what do you want to create') || label.includes('prompt');
              if (label.includes('tên dự án') || label.includes('project name')) return false;
              if (label.includes('search') || label.includes('tìm kiếm')) return false;
              if (tag === 'input' && r.y < 140 && !promptLike) return false;
              if (r.y < 40 && !promptLike && el.getAttribute('role') !== 'textbox') return false;
              return visible(el);
            });
        }
        """))
    except Exception:
        return False

async def dump_flow_composer_candidates(page, debug_dir: Path) -> None:
    try:
        data = await page.evaluate("""
        () => {
          function visible(el) {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 4 && r.height > 4 && s.visibility !== 'hidden' &&
              s.display !== 'none' && Number(s.opacity || 1) > 0.05;
          }
          function meta(el, index, kind) {
            const r = el.getBoundingClientRect();
            return {
              index, kind,
              tag: el.tagName.toLowerCase(),
              role: el.getAttribute('role') || '',
              ariaLabel: el.getAttribute('aria-label') || '',
              placeholder: el.getAttribute('placeholder') || '',
              text: (el.innerText || el.value || '').slice(0, 220),
              disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
              rect: {x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width), height: Math.round(r.height)}
            };
          }
          const editors = Array.from(document.querySelectorAll("textarea,[contenteditable='true'],[role='textbox'],input[type='text']"))
            .map((el, index) => ({el, index}))
            .filter(({el}) => !/recaptcha|g-recaptcha|hcaptcha/i.test(`${el.id || ''} ${el.name || ''} ${el.className || ''}`))
            .filter(({el}) => visible(el)).map(({el, index}) => meta(el, index, 'editor'));
          const buttons = Array.from(document.querySelectorAll('button,[role="button"],[aria-label]'))
            .filter(visible).filter(el => /arrow_forward|create|generate|submit|tạo|gửi/i.test(`${el.innerText || ''} ${el.getAttribute('aria-label') || ''}`))
            .map((el, index) => meta(el, index, 'submit'));
          return {url: location.href, editors, buttons};
        }
        """)
        (debug_dir / "flow_composer_candidates.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        log(f"WARN: không dump được composer candidates: {exc}")

async def find_flow_prompt_editor(page, debug_dir: Path):
    await dump_flow_composer_candidates(page, debug_dir)
    candidates = await page.locator(EDITOR_SELECTOR).evaluate_all("""
    els => els.map((el, index) => {
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      const visible = r.width > 20 && r.height > 12 && s.visibility !== 'hidden' && s.display !== 'none' && Number(s.opacity || 1) > 0.05;
      const label = `${el.getAttribute('aria-label') || ''} ${el.getAttribute('placeholder') || ''} ${el.innerText || el.value || ''}`.toLowerCase();
      const recaptcha = /recaptcha|g-recaptcha|hcaptcha/i.test(`${el.id || ''} ${el.name || ''} ${el.className || ''}`);
      const inTopBar = r.y < 140 || label.includes('search') || label.includes('tìm kiếm');
      const composerLike = el.hasAttribute('data-slate-editor') || el.closest('[data-slate-editor]') || el.closest('form') || el.closest('[class*="prompt" i]');
      let score = 0;
      if (visible) score += 20;
      if (recaptcha) score -= 1000;
      if (!inTopBar) score += 25;
      if (composerLike) score += 20;
      if (r.y > window.innerHeight * 0.35) score += 20;
      if (r.width > 220) score += 10;
      if (r.height >= 18) score += 5;
      if (inTopBar) score -= 100;
      return {index, score, visible, recaptcha, inTopBar, tag: el.tagName.toLowerCase(), rect: {x:r.x,y:r.y,width:r.width,height:r.height}};
    }).filter(x => x.visible && !x.recaptcha).sort((a,b) => b.score - a.score)
    """)
    for candidate in candidates:
        loc = page.locator(EDITOR_SELECTOR).nth(candidate["index"])
        try:
            await loc.wait_for(state="visible", timeout=1000)
            return loc, f"flow-composer-candidate[{candidate['index']}] score={candidate['score']} rect={candidate['rect']}"
        except Exception:
            continue
    return await first_visible(page, TEXTAREA_SELECTORS, timeout=3000)

async def fill_flow_prompt_editor(editor, prompt: str) -> None:
    await editor.evaluate("el => el.scrollIntoView({block: 'center', inline: 'center'})")
    await editor.click(timeout=5000)
    try:
        await editor.fill(prompt)
        return
    except Exception:
        pass
    await editor.evaluate("""
    (el, value) => {
      el.focus();
      if (el.isContentEditable) {
        el.innerText = value;
      } else {
        el.value = value;
      }
      el.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: value}));
      el.dispatchEvent(new Event('change', {bubbles: true}));
    }
    """, prompt)

async def fill_best_flow_prompt_editor(page, prompt: str, debug_dir: Path) -> str:
    result = await page.evaluate("""
    () => {
      function visible(el) {
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return r.width > 20 && r.height > 12 && s.visibility !== 'hidden' &&
          s.display !== 'none' && Number(s.opacity || 1) > 0.05;
      }
      function score(el) {
        const r = el.getBoundingClientRect();
        const label = `${el.getAttribute('aria-label') || ''} ${el.getAttribute('placeholder') || ''} ${el.innerText || el.value || ''}`.toLowerCase();
        const recaptcha = /recaptcha|g-recaptcha|hcaptcha/i.test(`${el.id || ''} ${el.name || ''} ${el.className || ''}`);
        const tag = el.tagName.toLowerCase();
        const promptLike = label.includes('bạn muốn tạo gì') || label.includes('what do you want to create') || label.includes('prompt');
        const projectNameLike = label.includes('tên dự án') || label.includes('project name') || (tag === 'input' && r.y < 140 && !promptLike);
        const inTopBar = (r.y < 140 && !promptLike) || label.includes('search') || label.includes('tìm kiếm');
        const composerLike = el.hasAttribute('data-slate-editor') || el.closest('[data-slate-editor]') || el.closest('form') || el.closest('[class*="prompt" i]');
        let s = 0;
        if (visible(el)) s += 20;
        if (recaptcha) s -= 1000;
        if (projectNameLike) s -= 1000;
        if (promptLike) s += 120;
        if (el.getAttribute('role') === 'textbox' && tag !== 'input') s += 80;
        if (!inTopBar) s += 25;
        if (composerLike) s += 20;
        if (r.y > window.innerHeight * 0.35) s += 20;
        if (r.width > 220) s += 10;
        if (r.height >= 18) s += 5;
        if (inTopBar) s -= 100;
        return s;
      }
      const elements = Array.from(document.querySelectorAll("textarea,[contenteditable='true'],[role='textbox'],input[type='text']"))
        .filter(el => !/recaptcha|g-recaptcha|hcaptcha/i.test(`${el.id || ''} ${el.name || ''} ${el.className || ''}`))
        .filter(visible)
        .map((el, index) => ({el, index, score: score(el)}))
        .filter(item => item.score > -500)
        .sort((a, b) => b.score - a.score);
      const chosen = elements[0];
      if (!chosen) return {ok: false, error: 'no_visible_non_recaptcha_editor'};
      const el = chosen.el;
      el.scrollIntoView({block: 'center', inline: 'center'});
      const r = el.getBoundingClientRect();
      return {
        ok: true,
        click: {
          x: Math.round(r.x + Math.min(Math.max(r.width / 2, 8), r.width - 8)),
          y: Math.round(r.y + Math.min(Math.max(r.height / 2, 8), r.height - 8))
        },
        detail: `dom-editor[${chosen.index}] score=${chosen.score} tag=${el.tagName.toLowerCase()} rect={x:${Math.round(r.x)},y:${Math.round(r.y)},width:${Math.round(r.width)},height:${Math.round(r.height)}}`
      };
    }
    """)
    (debug_dir / "flow_fill_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if not result or not result.get("ok"):
        raise RuntimeError(f"Không điền được prompt vào Flow editor: {(result or {}).get('error', 'unknown')}")
    click = result.get("click") or {}
    await page.mouse.click(float(click.get("x", 240)), float(click.get("y", 240)))
    await page.keyboard.press("Control+A")
    try:
        await page.keyboard.insert_text(prompt)
    except AttributeError:
        await page.keyboard.type(prompt, delay=1)
    return result.get("detail") or "dom-editor"

async def submit_flow_prompt(page, output_dir: Path, debug_dir: Path):
    for _ in range(20):
        await dump_flow_composer_candidates(page, debug_dir)
        submit, submit_selector = await first_visible(page, SUBMIT_SELECTORS, timeout=1000)
        if submit:
            disabled = await submit.evaluate("el => !!el.disabled || el.getAttribute('aria-disabled') === 'true'")
            log(f"Submit selector: {submit_selector} disabled={disabled}")
            if not disabled:
                await submit.click()
                return
        await page.wait_for_timeout(500)
    write_flow_bridge_status(output_dir, "submit_disabled", "needs_user_attention", "Flow submit vẫn bị disabled sau khi nhập prompt", 50, page.url)
    raise RuntimeError("Flow submit disabled after filling prompt. Có thể automation vẫn chưa chọn đúng composer, hoặc Google Flow yêu cầu chọn mode/model/quota/login trước khi tạo ảnh.")

async def open_flow_editor_if_needed(page) -> None:
    if await has_prompt_editor(page):
        return
    try:
        project_href = await page.evaluate("""
        () => {
          function visible(el) {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 20 && r.height > 20 && s.visibility !== 'hidden' &&
              s.display !== 'none' && Number(s.opacity || 1) > 0.05;
          }
          const link = Array.from(document.querySelectorAll('a[href*="/tools/flow/project/"],a[href*="/fx/vi/tools/flow/project/"],a[href*="/fx/tools/flow/project/"]'))
            .filter(visible)
            .find(a => !String(a.getAttribute('href') || '').includes('/_next/'));
          return link ? link.href : '';
        }
        """)
        if project_href:
            log(f"Open Flow project direct href: {project_href}")
            await page.goto(project_href, wait_until="domcontentloaded", timeout=30000)
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            for _ in range(12):
                if await has_prompt_editor(page):
                    return
                await page.wait_for_timeout(1000)
    except Exception as exc:
        log(f"WARN: mở project href trực tiếp chưa được: {exc}")
    for selector in PROJECT_SELECTORS:
        try:
            loc = page.locator(selector).first
            await loc.wait_for(state="visible", timeout=2500)
            log(f"Open Flow project selector: {selector}")
            await loc.click(timeout=5000)
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            for _ in range(10):
                if await has_prompt_editor(page):
                    return
                await page.wait_for_timeout(1000)
        except Exception:
            continue

async def goto_with_retry(page, url: str) -> None:
    last_error = None
    for attempt in range(1, 4):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            try:
                await page.wait_for_load_state("networkidle", timeout=30000)
            except Exception:
                pass
            return
        except Exception as exc:
            last_error = exc
            log(f"WARN: mở Flow lỗi lần {attempt}: {exc}")
            await page.wait_for_timeout(2500 * attempt)
    raise last_error


async def maybe_detect_block(page) -> Optional[str]:
    try:
        body = (await page.locator("body").inner_text(timeout=3000)).lower()
    except Exception:
        return None
    has_editor = False
    for selector in TEXTAREA_SELECTORS:
        try:
            if await page.locator(selector).first.is_visible(timeout=500):
                has_editor = True
                break
        except Exception:
            pass
    try:
        captcha_signals = await page.evaluate("""
        () => {
          function visible(el) {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 40 && r.height > 30 && s.visibility !== 'hidden' && s.display !== 'none' && Number(s.opacity || 1) > 0.05;
          }
          const frames = Array.from(document.querySelectorAll('iframe')).filter(visible)
            .map(f => `${f.title || ''} ${f.name || ''} ${f.src || ''}`.toLowerCase());
          const nodes = Array.from(document.querySelectorAll('[class],[id],[aria-label]')).filter(visible)
            .slice(0, 300)
            .map(el => `${el.id || ''} ${el.className || ''} ${el.getAttribute('aria-label') || ''} ${el.innerText || ''}`.toLowerCase());
          return frames.concat(nodes).filter(t =>
            t.includes('recaptcha') ||
            t.includes('g-recaptcha') ||
            t.includes('hcaptcha') ||
            t.includes('captcha') ||
            t.includes("i'm not a robot") ||
            t.includes('tôi không phải là người máy') ||
            t.includes('unusual traffic')
          ).slice(0, 8);
        }
        """)
        if captcha_signals and not has_editor:
            return "recaptcha_or_browser_challenge_detected"
    except Exception:
        pass
    if not has_editor:
        for pattern in HARD_BLOCK_PATTERNS:
            if pattern in body:
                return pattern
    if has_editor:
        return None
    for pattern in LOGIN_PATTERNS:
        if pattern in body:
            return pattern
    return None


async def save_largest_image_from_page(page, output_path: Path, debug_dir: Path) -> bool:
    images = await page.evaluate("""
    async () => {
      const imgs = Array.from(document.images || []);
      return imgs.map((img, index) => ({
        index,
        src: img.currentSrc || img.src || '',
        width: img.naturalWidth || img.width || 0,
        height: img.naturalHeight || img.height || 0,
        area: (img.naturalWidth || img.width || 0) * (img.naturalHeight || img.height || 0)
      })).filter(x => x.src && x.area >= 120000).sort((a,b) => b.area - a.area).slice(0, 8);
    }
    """)
    (debug_dir / "candidate_images.json").write_text(json.dumps(images, ensure_ascii=False, indent=2), encoding="utf-8")
    if not images:
        return False
    src = images[0]["src"]
    if src.startswith("data:image"):
        raw = src.split(",", 1)[1]
        temp = output_path.with_suffix(".download")
        temp.write_bytes(base64.b64decode(raw))
        ensure_jpeg(temp, output_path)
        temp.unlink(missing_ok=True)
        return output_path.exists() and output_path.stat().st_size > 0
    if src.startswith("blob:"):
        data_url = await page.evaluate("""
        async (url) => {
          const res = await fetch(url);
          const blob = await res.blob();
          return await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onloadend = () => resolve(reader.result);
            reader.onerror = reject;
            reader.readAsDataURL(blob);
          });
        }
        """, src)
        raw = data_url.split(",", 1)[1]
        temp = output_path.with_suffix(".download")
        temp.write_bytes(base64.b64decode(raw))
        ensure_jpeg(temp, output_path)
        temp.unlink(missing_ok=True)
        return output_path.exists() and output_path.stat().st_size > 0
    response = await page.request.get(src, timeout=30000)
    if response.ok:
        temp = output_path.with_suffix(".download")
        temp.write_bytes(await response.body())
        ensure_jpeg(temp, output_path)
        temp.unlink(missing_ok=True)
        return output_path.exists() and output_path.stat().st_size > 0
    return False


def _write_prompt_with_reference(output_dir: Path, reference: dict,
                                 gen_mode: str, upload_status: str,
                                 hero_reference: Path = None) -> None:
    """Ghi prompt_with_reference.json: prompt upload + text-only + selected reference + upload status.

    Đọc 2 variant thật từ thumbnail_image_prompt.json (sinh ở build_image_plan_and_prompt).
    Cập nhật thumbnail_prompt.txt + image_prompt.prompt_text = variant đã dùng theo gen_mode.
    """
    try:
        hero_reference = Path(hero_reference) if hero_reference else (output_dir / "thumbnail_reference.jpg")
        ref_report = _load_json(output_dir / "reference_selection_report.json")
        image_prompt = _load_json(output_dir / "thumbnail_image_prompt.json")
        prompt_upload = image_prompt.get("prompt_upload") or image_prompt.get("prompt_text") or ""
        prompt_text_only = image_prompt.get("prompt_text_only") or image_prompt.get("prompt_text") or ""
        selected_ref = {}
        if hero_reference.exists():
            selected_ref = {
                "path": str(hero_reference),
                "source": ref_report.get("winner_source", reference.get("source", "")),
                "score": ref_report.get("winner_score"),
            }
        upload_used = gen_mode == "reference_upload"
        # Variant thật sự đã dùng: upload -> prompt_upload, text-only -> prompt_text_only.
        prompt_used = prompt_upload if upload_used else prompt_text_only
        payload = {
            "prompt_upload": prompt_upload,
            "prompt_text_only": prompt_text_only,
            "prompt_used": prompt_used,
            "selected_reference": selected_ref,
            "upload_requested": FLOW_REFERENCE_UPLOAD,
            "upload_used": upload_used,
            "upload_required": FLOW_REFERENCE_UPLOAD_REQUIRED,
            "upload_status": upload_status,
            "generation_mode": gen_mode,
        }
        (output_dir / "prompt_with_reference.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        # Cập nhật prompt thật đã dùng vào thumbnail_prompt.txt + image_prompt.prompt_text.
        if prompt_used:
            (output_dir / "thumbnail_prompt.txt").write_text(prompt_used + "\n", encoding="utf-8")
            image_prompt["prompt_text"] = prompt_used
            image_prompt["generation_mode"] = gen_mode
            (output_dir / "thumbnail_image_prompt.json").write_text(
                json.dumps(image_prompt, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        log(f"WARN: ghi prompt_with_reference.json failed: {exc}")


async def generate_via_flow(page, output_dir: Path, prompt: str, thumbnail: Path, debug_dir: Path) -> None:
    """Fill, upload reference (best-effort), submit, and download the generated image.
    Raises on hard failure so the caller can fallback / retry.
    """
    log(f"Opening Google Flow: {FLOW_URL}")
    write_flow_bridge_status(output_dir, "open_flow", "running", f"Đang mở Google Flow: {FLOW_URL}", 28)
    await goto_with_retry(page, FLOW_URL)
    block = await maybe_detect_block(page)
    if block:
        write_flow_bridge_status(output_dir, "user_attention", "needs_user_attention", block, 30, page.url)
        raise RuntimeError(f"Google Flow có dấu hiệu cần can thiệp/login/quota/captcha: {block}")

    await open_flow_editor_if_needed(page)
    write_flow_bridge_status(output_dir, "editor_ready", "running", "Đã vào editor Google Flow", 38, page.url)

    # Best-effort reference upload (non-fatal unless FLOW_REFERENCE_UPLOAD_REQUIRED=1).
    hero_reference = output_dir / "thumbnail_reference.jpg"
    try:
        gen_mode = await upload_reference_to_flow(page, hero_reference, debug_dir)
    except Exception:  # noqa: BLE001
        gen_mode = "reference_prompt_only"
    try:
        plan_path = output_dir / "thumbnail_image_plan.json"
        if plan_path.exists():
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["generation_mode"] = gen_mode
            plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    if gen_mode == "reference_prompt_only":
        log("generation_mode=reference_prompt_only (không có upload UI hoặc upload fail).")

    # Ghi prompt_with_reference.json: prompt upload + text-only + selected reference + upload status.
    upload_status = _load_json(debug_dir / "flow_upload_status.json").get("status", "unknown")
    _write_prompt_with_reference(output_dir, {"source": ""}, gen_mode, upload_status,
                                 hero_reference=hero_reference)

    # Task 2: required upload mà fail -> fail rõ ràng thay vì âm thầm prompt-only.
    if FLOW_REFERENCE_UPLOAD_REQUIRED and gen_mode != "reference_upload":
        msg = (f"FLOW_REFERENCE_UPLOAD_REQUIRED=1 nhưng upload reference thất bại "
               f"(gen_mode={gen_mode}, upload_status={upload_status}). Từ chối fallback prompt-only.")
        log(f"ERROR: {msg}")
        write_flow_bridge_status(output_dir, "upload_required_failed", "needs_user_attention",
                                 msg, 40, page.url)
        raise RuntimeError(msg)

    # Chọn prompt variant theo gen_mode: upload -> prompt_upload (nói rõ có ảnh kèm),
    # text-only -> prompt_text_only (mô tả bằng text, không giả vờ có ảnh).
    image_prompt = _load_json(output_dir / "thumbnail_image_prompt.json")
    prompt_upload = image_prompt.get("prompt_upload") or prompt
    prompt_text_only = image_prompt.get("prompt_text_only") or prompt
    prompt_used = prompt_upload if gen_mode == "reference_upload" else prompt_text_only

    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)
    except Exception:
        pass
    editor_selector = await fill_best_flow_prompt_editor(page, prompt_used, debug_dir)
    log(f"Prompt editor selector: {editor_selector}")
    await page.wait_for_timeout(1000)
    write_flow_bridge_status(output_dir, "prompt_filled", "running", "Đã nhập prompt vào Google Flow", 48, page.url)

    await submit_flow_prompt(page, output_dir, debug_dir)
    write_flow_bridge_status(output_dir, "submitted", "running", "Đã gửi prompt, đang chờ Flow tạo ảnh", 55, page.url)

    deadline = time.time() + GENERATION_WAIT_SECONDS
    while time.time() < deadline:
        remaining = max(0, deadline - time.time())
        elapsed = GENERATION_WAIT_SECONDS - remaining
        wait_progress = 55 + int(min(30, (elapsed / max(1, GENERATION_WAIT_SECONDS)) * 30))
        write_flow_bridge_status(output_dir, "waiting_generation", "running", "Đang chờ ảnh final từ Google Flow", wait_progress, page.url)
        if thumbnail.exists() and thumbnail.stat().st_size > 0:
            break
        block = await maybe_detect_block(page)
        if block:
            write_flow_bridge_status(output_dir, "user_attention", "needs_user_attention", block, wait_progress, page.url)
            raise RuntimeError(f"Google Flow báo cần can thiệp/quota/captcha sau khi submit: {block}")

        download, download_selector = await first_visible(page, DOWNLOAD_SELECTORS, timeout=2000)
        if download:
            log(f"Download selector: {download_selector}")
            try:
                async with page.expect_download(timeout=8000) as download_info:
                    await download.click()
                dl = await download_info.value
                temp_path = output_dir / ("thumbnail_flow_download" + Path(dl.suggested_filename).suffix)
                await dl.save_as(str(temp_path))
                ensure_jpeg(temp_path, thumbnail)
                temp_path.unlink(missing_ok=True)
            except PlaywrightTimeoutError:
                await download.click()
            except Exception as exc:
                log(f"WARN: download click chưa lấy được file: {exc}")

        if not thumbnail.exists() or thumbnail.stat().st_size == 0:
            try:
                if await save_largest_image_from_page(page, thumbnail, debug_dir):
                    log("Saved thumbnail from largest page image")
                    break
            except Exception as exc:
                log(f"WARN: chưa trích xuất được ảnh từ page: {exc}")
        await page.wait_for_timeout(5000)

    if not thumbnail.exists() or thumbnail.stat().st_size == 0:
        write_flow_bridge_status(output_dir, "download_missing", "needs_user_attention", "Hết thời gian chờ nhưng chưa lấy được ảnh", 86, page.url)
        raise RuntimeError("Hết thời gian chờ nhưng chưa lấy được thumbnail final từ Google Flow.")


def _gate_should_retry(report: dict) -> bool:
    """Retry nếu gate flag fixable problems. retry_action: composer_reroll (rẻ) hoặc flow_regen (đắt)."""
    if not THUMBNAIL_QUALITY_GATE_ENABLED:
        return False
    if report.get("status") not in ("needs_attention", "warning"):
        return False
    action = report.get("retry_action", "none")
    return action in ("composer_reroll", "flow_regen")


async def run(output_dir: Path) -> int:
    started = time.time()
    output_dir = output_dir.resolve()
    base_dir = output_dir.parent
    debug_dir = output_dir / "google_flow_debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    thumbnail = output_dir / "thumbnail.jpg"
    prompt_file = output_dir / "thumbnail_prompt.txt"
    title_file = output_dir / "thumbnail_title.txt"
    latest_thumbnail = base_dir / "LATEST_THUMBNAIL.txt"
    latest_prompt = base_dir / "LATEST_THUMBNAIL_PROMPT.txt"

    thumbnail.unlink(missing_ok=True)
    write_flow_bridge_status(output_dir, "prepare", "running", "Chuẩn bị creative + reference + prompt cho Google Flow", 5)

    # 1. Creative: story analysis + hook.
    creative = prepare_creative(output_dir, debug_dir)
    hook = creative.get("hook") or ""
    if not hook:
        # Last-resort heuristic title (NOT the old choose_title keyword table unless creative totally absent).
        story_path = output_dir / "thumbnail_story_analysis.json"
        if story_path.exists():
            try:
                story = json.loads(story_path.read_text(encoding="utf-8"))
                hook = (story.get("main_conflict") or "").upper()[:48] or "KHOẢNH KHẮC KỊCH TÍNH"
            except Exception:
                hook = "KHOẢNH KHẮC KỊCH TÍNH"
        else:
            # Creative module produced nothing at all -> keep legacy choose_title available.
            vi = read_srt(output_dir / "vietnamese.srt")
            hook = choose_title(vi or output_dir.name)
    angle = creative.get("selected_angle") or "khoảnh khắc kịch tính"
    write_flow_bridge_status(output_dir, "creative_ready", "running", f"Hook: {hook}", 8)
    log(f"Thumbnail title/hook: {hook}")

    # 2. Discover character references (multi-frame + vision rerank) -> legacy reference.jpg too.
    reference = discover_references(output_dir, angle, hook, debug_dir)
    write_flow_bridge_status(output_dir, "reference_ready", "running", "Đã chọn reference nhân vật", 12)

    # 2b. Optional visual-aware hook refine (sau khi có reference visual analysis).
    if THUMBNAIL_REFINE_HOOK and THUMBNAIL_CREATIVE_ENABLED:
        try:
            code, out = run_helper("thumbnail_creative.py", str(output_dir), "--refine")
            (debug_dir / "thumbnail_creative_refine.log").write_text(out, encoding="utf-8", errors="replace")
            if code == 0:
                sel = _load_json(output_dir / "thumbnail_hook_selected.json")
                refined_hook = (sel.get("hook") or "").strip()
                if refined_hook and refined_hook != hook:
                    log(f"Hook refined từ visual: {hook} -> {refined_hook} (seed={sel.get('seed_hook')})")
                    hook = refined_hook
                    creative["hook"] = hook
        except Exception as exc:
            log(f"WARN: refine hook failed (giữ seed): {exc}")

    # 3. Text plan TRƯỚC image plan/prompt để image prompt biết text layout thật
    #    (anchor/negative_space_for_text) và chừa đúng vùng cho chữ Việt local.
    build_text_plan(output_dir, hook)
    write_flow_bridge_status(output_dir, "text_plan_ready", "running", "Đã tạo text plan (layout chữ Việt)", 13)

    # 4. Build image plan + prompt (đọc text_plan đã có cho negative_space_for_text).
    hook, prompt, image_plan = build_image_plan_and_prompt(output_dir, creative, reference)
    title_file.write_text(hook + "\n", encoding="utf-8")
    prompt_file.write_text(prompt + "\n", encoding="utf-8")
    write_flow_bridge_request(output_dir, hook, prompt)
    write_flow_bridge_status(output_dir, "prompt_ready", "running", "Đã tạo image plan + prompt bridge", 15)

    # Dry-run: produce all artifacts, skip Chrome/Flow, exit 0.
    if THUMBNAIL_DRY_RUN:
        log("THUMBNAIL_DRY_RUN=1: skipping Chrome/Flow; artifacts written. Exit 0.")
        # Write prompt_with_reference.json (dry-run không chạy upload -> text-only mode).
        _write_prompt_with_reference(output_dir, reference, "reference_prompt_only",
                                     "dry_run_no_flow", hero_reference=output_dir / "thumbnail_reference.jpg")
        # Build a local fallback thumbnail so the dry-run produces thumbnail.jpg too.
        create_local_fallback_thumbnail(output_dir, thumbnail, hook, debug_dir, "dry_run")
        # Run quality gate against the fallback so the report is present.
        if THUMBNAIL_QUALITY_GATE_ENABLED and thumbnail.exists():
            report = quality_gate(output_dir, thumbnail, hook, reference)
            log(f"Dry-run quality report: status={report.get('status')} overall={report.get('overall')}")
        latest_thumbnail.write_text(str(thumbnail) + "\n", encoding="utf-8")
        latest_prompt.write_text(str(prompt_file) + "\n", encoding="utf-8")
        write_flow_bridge_status(output_dir, "dry_run_done", "done", "Dry-run hoàn tất: artifacts + fallback thumbnail", 100)
        log(f"HOÀN TẤT dry-run: {thumbnail}")
        return 0

    async with async_playwright() as playwright:
        browser, cdp_url = await connect_browser(playwright)
        write_flow_bridge_status(output_dir, "connect_cdp", "running", f"Đã kết nối Chrome CDP: {cdp_url}", 20)
        context = browser.contexts[0] if browser.contexts else await browser.new_context(accept_downloads=True)
        page = await context.new_page()
        page.set_default_timeout(20000)
        try:
            # 5-6. Generate via Flow (upload + fill + submit + download).
            await generate_via_flow(page, output_dir, prompt, thumbnail, debug_dir)

            raw_thumbnail = output_dir / "thumbnail_flow_raw.jpg"
            if thumbnail.exists() and not raw_thumbnail.exists():
                try:
                    shutil.copy2(thumbnail, raw_thumbnail)
                except Exception:
                    pass
            # 7. Compose Vietnamese text locally.
            write_flow_bridge_status(output_dir, "compose_text", "running", "Đã có ảnh Flow, đang chèn chữ Việt local", 90, page.url)
            compose_vietnamese_text(thumbnail, hook, output_dir, debug_dir)

            # 8. Quality gate (smart retry: composer_reroll rẻ / flow_regen đắt).
            report = {"status": "pass"}
            if THUMBNAIL_QUALITY_GATE_ENABLED and thumbnail.exists():
                report = quality_gate(output_dir, thumbnail, hook, reference)
                log(f"Quality gate: status={report.get('status')} overall={report.get('overall')} action={report.get('retry_action')}")
                if _gate_should_retry(report):
                    action = report.get("retry_action", "none")
                    if action == "composer_reroll":
                        # Rẻ: chỉ re-compose với force-large settings (không regenerate Flow).
                        log("Quality gate -> composer_reroll (force-large text, không regen Flow).")
                        write_flow_bridge_status(output_dir, "quality_retry", "running", "Text fail -> re-compose force-large", 92, page.url)
                        try:
                            _compose_force_large(thumbnail, hook, output_dir, debug_dir)
                            report = quality_gate(output_dir, thumbnail, hook, reference)
                            log(f"Quality gate (composer reroll): status={report.get('status')}")
                        except Exception as retry_exc:
                            log(f"WARN: composer reroll lỗi: {retry_exc}")
                    elif action == "flow_regen" and THUMBNAIL_FLOW_RETRY > 0:
                        # Đắt: regenerate Flow 1 lần.
                        log("Quality gate -> flow_regen (xoá ảnh cũ, regen Flow 1 lần).")
                        write_flow_bridge_status(output_dir, "quality_retry", "running", "Ảnh tối/rối -> regen Flow 1 lần", 70, page.url)
                        thumbnail.unlink(missing_ok=True)
                        try:
                            await generate_via_flow(page, output_dir, prompt, thumbnail, debug_dir)
                            if thumbnail.exists():
                                compose_vietnamese_text(thumbnail, hook, output_dir, debug_dir)
                                report = quality_gate(output_dir, thumbnail, hook, reference)
                                log(f"Quality gate (flow retry): status={report.get('status')}")
                        except Exception as retry_exc:
                            log(f"WARN: retry regen lỗi: {retry_exc}")

            latest_thumbnail.write_text(str(thumbnail) + "\n", encoding="utf-8")
            latest_prompt.write_text(str(prompt_file) + "\n", encoding="utf-8")
            clear_attention_report(output_dir, page.url)
            write_flow_bridge_status(output_dir, "done", "done", "Hoàn tất thumbnail bằng Google Flow + chữ Việt local", 100, page.url)
            log(f"HOÀN TẤT thumbnail: {thumbnail}")
            log(f"Elapsed: {int(time.time() - started)}s | CDP: {cdp_url}")
            return 0
        except Exception as exc:
            detail = str(exc)
            reason = classify_flow_error(detail)
            log(f"ERROR: {detail}")
            try:
                await page.screenshot(path=str(debug_dir / "error.png"), full_page=True)
                (debug_dir / "error.html").write_text(await page.content(), encoding="utf-8", errors="ignore")
                (debug_dir / "error_url.txt").write_text(page.url + "\n", encoding="utf-8")
            except Exception:
                pass
            try:
                write_attention_report(output_dir, reason, detail, page.url)
                write_flow_bridge_status(output_dir, "fallback", "needs_user_attention", detail, 90, page.url, {"reason": reason})
            except Exception as report_exc:
                log(f"WARN: không ghi được thumbnail_flow_status.json: {report_exc}")
            # 9. Local fallback: never fail the video pipeline if a valid thumbnail can be made.
            if create_local_fallback_thumbnail(output_dir, thumbnail, hook, debug_dir, reason):
                # Compose Vietnamese text on the fallback too (best-effort).
                try:
                    compose_vietnamese_text(thumbnail, hook, output_dir, debug_dir)
                except Exception:
                    overlay_vietnamese_title(thumbnail, hook, debug_dir)
                if THUMBNAIL_QUALITY_GATE_ENABLED and thumbnail.exists():
                    fb_report = quality_gate(output_dir, thumbnail, hook, reference)
                    fb_report["status"] = "failed_fallback_used"
                    (output_dir / "thumbnail_quality_report.json").write_text(
                        json.dumps(fb_report, ensure_ascii=False, indent=2), encoding="utf-8")
                latest_thumbnail.write_text(str(thumbnail) + "\n", encoding="utf-8")
                latest_prompt.write_text(str(prompt_file) + "\n", encoding="utf-8")
                write_flow_bridge_status(output_dir, "fallback_done", "fallback_done", "Đã tạo thumbnail fallback local; cần user xử lý Flow nếu muốn ảnh Flow", 100, page.url, {"reason": reason})
                log("WARN_USER_ACTION_REQUIRED: Thumbnail hiện tại là fallback local vì Google Flow cần can thiệp.")
                log(f"HOÀN TẤT thumbnail fallback: {thumbnail}")
                return 0
            return 1
        finally:
            try:
                await page.close()
            except Exception:
                pass


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: google_flow_thumbnail.py OUTPUT_DIR", file=sys.stderr)
        return 2
    try:
        return asyncio.run(run(Path(sys.argv[1])))
    except Exception as exc:
        log(f"FATAL: {exc}")
        output_dir = Path(sys.argv[1]).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        write_flow_bridge_status(
            output_dir,
            "fatal",
            "needs_user_attention",
            str(exc),
            100,
            extra={"reason": classify_flow_error(str(exc))},
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
