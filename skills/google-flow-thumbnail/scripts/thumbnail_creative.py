#!/usr/bin/env python3
"""Creative analysis + hook ideation for the thumbnail pipeline.

Reads vietnamese.srt / dub.srt / original.srt / source_input.txt / final_metadata.json
and asks a local Ollama model (POST /api/chat, stream:false, think:false) to:
  1. analyze the story,
  2. ideate 10-20 short Vietnamese hooks,
  3. score each hook 0-10,
  4. pick the final hook (top-5, with a reason).

Fail-open by design: if Ollama is unavailable / errors / returns garbage, a heuristic
story summary and a hook derived from it are produced. The caller never crashes and
the video pipeline keeps running. We do NOT fall back to the old choose_title() keyword
heuristic except as a last-resort label.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

CREATIVE_ENABLED = os.environ.get("THUMBNAIL_CREATIVE_ENABLED", "1") != "0"
API_BASE = os.environ.get("THUMBNAIL_CREATIVE_API_BASE", "http://127.0.0.1:11434").rstrip("/")
CREATIVE_MODEL = os.environ.get("THUMBNAIL_CREATIVE_MODEL") or os.environ.get("OLLAMA_MODEL") or "minimax-m3:cloud"
TIMEOUT = int(float(os.environ.get("THUMBNAIL_CREATIVE_TIMEOUT_SECONDS", "90")))
ANALYSIS_TEMP = float(os.environ.get("THUMBNAIL_CREATIVE_ANALYSIS_TEMP", "0.15"))
HOOK_TEMP = float(os.environ.get("THUMBNAIL_CREATIVE_HOOK_TEMP", "0.5"))
FAIL_OPEN = os.environ.get("THUMBNAIL_CREATIVE_FAIL_OPEN", "1") != "0"

# Hooks that are too generic / placeholder-y to ever ship.
GENERIC_HOOKS = {
    "biến cố bất ngờ", "sự kiện bất ngờ", "kỷ nguyên mới", "câu chuyện bắt đầu",
    "hậu quả khôn lường", "mọi thứ đổi thay", "bắt đầu rồi", "không thể tin nổi",
}

VIETNAMESE_STOP = set(
    "và là của với để trong một các cái này đó những cho được sẽ có cũng lên xuống ra vào "
    "đã đang thì mà nhưng trên dưới kia này nọ anh chị ông bà con em".split()
)


def log(msg: str) -> None:
    print(f"thumbnail_creative: {msg}", flush=True)


def read_srt(path: Path, limit: int = 9000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="ignore")
    text = re.sub(r"\d+\s+\d{2}:\d{2}:\d{2},\d{3}\s+-->\s+\d{2}:\d{2}:\d{2},\d{3}", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def read_text(path: Path, limit: int = 4000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip()[:limit]
    except Exception:
        return ""


def gather_corpus(output_dir: Path) -> dict:
    vi = read_srt(output_dir / "vietnamese.srt")
    dub = read_srt(output_dir / "dub.srt")
    orig = read_srt(output_dir / "original.srt", 4000)
    source = read_text(output_dir / "source_input.txt")
    meta = ""
    meta_path = output_dir / "final_metadata.json"
    if meta_path.exists():
        try:
            m = json.loads(meta_path.read_text(encoding="utf-8", errors="ignore"))
            title = (m.get("inputs") or {}).get("title") or (m.get("metadata") or {}).get("title")
            if title:
                meta = str(title)[:300]
        except Exception:
            pass
    return {"vi": vi, "dub": dub, "orig": orig, "source": source, "meta": meta}


def corpus_seed(corpus: dict) -> str:
    return corpus["vi"] or corpus["dub"] or corpus["orig"] or corpus["source"] or corpus["meta"]


def chat(model: str, messages: list[dict], temperature: float) -> tuple[Optional[str], Optional[str]]:
    """POST /api/chat with stream:false, think:false. Returns (content, error)."""
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"temperature": temperature},
    }).encode("utf-8")
    req = urllib.request.Request(
        API_BASE + "/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except TimeoutError:
        return None, "timeout"
    except urllib.error.URLError as exc:
        return None, f"url_error: {exc.reason if hasattr(exc, 'reason') else exc}"
    except Exception as exc:  # noqa: BLE001
        return None, f"error: {exc}"
    msg = data.get("message") or {}
    content = str(msg.get("content") or "").strip()
    if not content:
        return None, "empty_response"
    return content, None


def _extract_json_block(text: str) -> str:
    """Pull the first {...} or [...] JSON block out of a model reply."""
    for i, ch in enumerate(text):
        if ch in "{[":
            opener = ch
            closer = "}" if opener == "{" else "]"
            depth = 0
            in_str = False
            esc = False
            for j in range(i, len(text)):
                c = text[j]
                if in_str:
                    if esc:
                        esc = False
                    elif c == "\\":
                        esc = True
                    elif c == '"':
                        in_str = False
                    continue
                if c == '"':
                    in_str = True
                elif c == opener:
                    depth += 1
                elif c == closer:
                    depth -= 1
                    if depth == 0:
                        return text[i:j + 1]
            break
    return text.strip()


ANALYSIS_SYSTEM = (
    "Bạn là biên kịch phân tích video ngắn để làm thumbnail YouTube tiếng Việt. "
    "Trả về JSON hợp lệ, không markdown, không giải thích ngoài JSON."
)
ANALYSIS_PROMPT = """Phân tích video sau để làm thumbnail YouTube kịch tính, không spoil cốt truyện.

Nội dung (phụ đề/mô tả nguồn):
{seed}

Trả về JSON đúng schema:
{{
  "core_plot": "1 câu tóm tắt xung đột chính (<=140 ký tự)",
  "main_character": "nhân vật/chủ thể chính + vai trò (<=120 ký tự)",
  "main_conflict": "xung đột/mục tiêu chính (<=140 ký tự)",
  "strongest_emotion": "cảm xúc mạnh nhất người xem thấy (sợ/giận/ngạc nhiên/tò mò...)",
  "mystery_or_secret": "bí mật/câu hỏi mở hấp dẫn nếu có, hoặc \"\"",
  "danger_or_threat": "mối đe dọa/nguy hiểm nếu có, hoặc \"\"",
  "twist_or_reversal": "bước ngoặt/twist nếu có, hoặc \"\"",
  "clickable_angles": ["3-5 góc nhìn thumbnail kịch tính, ngắn, không spoil"]
}}

Chỉ trả JSON."""


HOOK_SYSTEM = (
    "Bạn là chuyên gia copywriting thumbnail YouTube tiếng Việt. Hook phải 2-6 từ, "
    "viết hoa, giật, cụ thể với nội dung, KHÔNG spoil, KHÔNG chép nguyên lời thoại. "
    "Trả về JSON hợp lệ, không markdown, không giải thích ngoài JSON."
)
HOOK_PROMPT = """Dựa trên phân tích story, viết 12-18 hook thumbnail tiếng Việt (2-6 từ mỗi hook).

Story:
- cốt truyện: {core_plot}
- nhân vật chính: {main_character}
- xung đột: {main_conflict}
- cảm xúc mạnh: {strongest_emotion}
- bí mật: {mystery}
- đe dọa: {danger}
- twist: {twist}

Quy tắc: viết hoa, giật, cụ thể, không spoiler, không chép lời thoại, không generic như "BIẾN CỐ BẤT NGỜ".

Trả về JSON:
{{
  "hooks": [
    {{"text": "HOOK 1"}},
    {{"text": "HOOK 2"}}
  ]
}}

Chỉ trả JSON."""


SCORE_PROMPT = """Chấm từng hook 0-10 theo 6 tiêu chí cho thumbnail YouTube tiếng Việt:
- content_accuracy: đúng nội dung video
- curiosity: gây tò mò
- clarity_in_1_second: đọc hiểu ngay trong 1 giây trên mobile
- specificity: cụ thể với video này, không dùng được cho video khác
- spoiler_risk: 10=an toàn không spoil, 0=spoil hết
- ctr_potential: khả năng click

Story ngắn: {core_plot} | xung đột: {main_conflict} | cảm xúc: {strongest_emotion}

Hooks:
{hook_list}

Trả về JSON:
{{
  "scores": [
    {{"hook": "HOOK", "content_accuracy": N, "curiosity": N, "clarity_in_1_second": N, "specificity": N, "spoiler_risk": N, "ctr_potential": N}}
  ]
}}

Chỉ trả JSON."""


def heuristic_story(corpus: dict, reason: str) -> dict:
    seed = corpus_seed(corpus)
    words = re.findall(r"[A-Za-zÀ-ỹ0-9]+", seed)
    summary = " ".join(words[:24])
    if not summary:
        summary = corpus["source"] or corpus["meta"] or "video recap"
    return {
        "status": "heuristic_fallback",
        "fallback_reason": reason,
        "model": CREATIVE_MODEL,
        "core_plot": summary[:140],
        "main_character": "nhân vật chính trong video",
        "main_conflict": "xung đột trung tâm trong video",
        "strongest_emotion": "kịch tính",
        "mystery_or_secret": "",
        "danger_or_threat": "",
        "twist_or_reversal": "",
        "clickable_angles": ["khoảnh khắc kịch tính", "biểu cảm nhân vật", "đối đầu"],
    }


def analyze_story(corpus: dict) -> tuple[dict, Optional[str]]:
    if not CREATIVE_ENABLED:
        return heuristic_story(corpus, "creative_disabled"), "creative_disabled"
    seed = corpus_seed(corpus)
    if not seed:
        return heuristic_story(corpus, "empty_corpus"), "empty_corpus"
    content, err = chat(
        CREATIVE_MODEL,
        [
            {"role": "system", "content": ANALYSIS_SYSTEM},
            {"role": "user", "content": ANALYSIS_PROMPT.format(seed=seed[:2600])},
        ],
        ANALYSIS_TEMP,
    )
    if not content:
        return heuristic_story(corpus, f"analysis_call_failed: {err}"), err or "analysis_call_failed"
    try:
        parsed = json.loads(_extract_json_block(content))
    except Exception:
        return heuristic_story(corpus, f"analysis_parse_failed: {content[:120]}"), "analysis_parse_failed"
    # Normalize keys + keep extra fields.
    norm = {"status": "ok", "model": CREATIVE_MODEL}
    for key in ("core_plot", "main_character", "main_conflict", "strongest_emotion",
               "mystery_or_secret", "danger_or_threat", "twist_or_reversal"):
        norm[key] = str(parsed.get(key) or "")[:300]
    angles = parsed.get("clickable_angles") or []
    if isinstance(angles, list) and angles:
        norm["clickable_angles"] = [str(a).strip()[:140] for a in angles if str(a).strip()][:6]
    else:
        norm["clickable_angles"] = ["khoảnh khắc kịch tính"]
    return norm, None


def _normalize_hook(raw) -> Optional[str]:
    text = str(raw or "").strip().upper()
    text = re.sub(r'^["\-\*\d.\)\s]+', "", text)
    text = re.sub(r'["\*\s]+$', "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    words = text.split()
    if len(words) < 2 or len(words) > 8:  # 2-8 tokens tolerance for VN compound words
        return None
    if len(text) < 4 or len(text) > 48:
        return None
    if text.lower() in GENERIC_HOOKS:
        return None
    return text


def ideate_hooks(story: dict) -> tuple[list[str], Optional[str]]:
    if story.get("status") != "ok":
        # Heuristic path: derive a couple hooks from story summary (not choose_title keywords).
        return _heuristic_hooks(story), story.get("fallback_reason") or "heuristic_story"
    content, err = chat(
        CREATIVE_MODEL,
        [
            {"role": "system", "content": HOOK_SYSTEM},
            {"role": "user", "content": HOOK_PROMPT.format(
                core_plot=story.get("core_plot", ""),
                main_character=story.get("main_character", ""),
                main_conflict=story.get("main_conflict", ""),
                strongest_emotion=story.get("strongest_emotion", ""),
                mystery=story.get("mystery_or_secret") or "",
                danger=story.get("danger_or_threat") or "",
                twist=story.get("twist_or_reversal") or "",
            )},
        ],
        HOOK_TEMP,
    )
    if not content:
        return _heuristic_hooks(story), f"ideate_call_failed: {err}"
    try:
        parsed = json.loads(_extract_json_block(content))
    except Exception:
        return _heuristic_hooks(story), f"ideate_parse_failed: {content[:120]}"
    raw_hooks = parsed.get("hooks") if isinstance(parsed, dict) else parsed
    hooks: list[str] = []
    seen = set()
    if isinstance(raw_hooks, list):
        for item in raw_hooks:
            text = item.get("text") if isinstance(item, dict) else item
            norm = _normalize_hook(text)
            if norm and norm.lower() not in seen:
                seen.add(norm.lower())
                hooks.append(norm)
    if len(hooks) < 3:
        return _heuristic_hooks(story), "too_few_valid_hooks"
    return hooks[:20], None


def _heuristic_hooks(story: dict) -> list[str]:
    """Build hooks from story summary without the old choose_title keyword table."""
    conflict = story.get("main_conflict", "")
    emotion = story.get("strongest_emotion", "")
    core = story.get("core_plot", "")
    candidates = []
    if conflict and conflict != "xung đột trung tâm trong video":
        candidates.append(conflict[:48].upper())
    if emotion and emotion != "kịch tính":
        candidates.append(f"{emotion.upper()} ĐẾN CÙNG")
    if core:
        words = re.findall(r"[A-Za-zÀ-ỹ0-9]+", core)
        keywords = [w for w in words if w.lower() not in VIETNAMESE_STOP and len(w) > 2]
        if len(keywords) >= 2:
            candidates.append(" ".join(keywords[:4]).upper()[:48])
    candidates = [c for c in candidates if c.lower() not in GENERIC_HOOKS]
    if not candidates:
        candidates = ["KHOẢNH KHẮC KỊCH TÍNH"]
    # Dedup + cap.
    seen, out = set(), []
    for c in candidates:
        if c.lower() not in seen:
            seen.add(c.lower())
            out.append(c)
    return out[:6]


def score_hooks(hooks: list[str], story: dict) -> tuple[list[dict], Optional[str]]:
    if story.get("status") != "ok" or len(hooks) <= 3:
        # Heuristic scoring: emphasize specificity + ctr for hooks derived from story.
        return _heuristic_scores(hooks), None
    hook_list = "\n".join(f"{i+1}. {h}" for i, h in enumerate(hooks))
    content, err = chat(
        CREATIVE_MODEL,
        [
            {"role": "system", "content": "Bạn là thẩm phán thumbnail. Trả JSON hợp lệ, không markdown."},
            {"role": "user", "content": SCORE_PROMPT.format(
                core_plot=story.get("core_plot", ""),
                main_conflict=story.get("main_conflict", ""),
                strongest_emotion=story.get("strongest_emotion", ""),
                hook_list=hook_list,
            )},
        ],
        ANALYSIS_TEMP,
    )
    if not content:
        return _heuristic_scores(hooks), f"score_call_failed: {err}"
    try:
        parsed = json.loads(_extract_json_block(content))
    except Exception:
        return _heuristic_scores(hooks), "score_parse_failed"
    raw = parsed.get("scores") if isinstance(parsed, dict) else parsed
    if not isinstance(raw, list):
        return _heuristic_scores(hooks), "score_no_list"
    scored: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        h = _normalize_hook(item.get("hook"))
        if not h or h.lower() not in {x.lower() for x in hooks}:
            continue
        s = {
            "hook": h,
            "content_accuracy": _clamp(item.get("content_accuracy")),
            "curiosity": _clamp(item.get("curiosity")),
            "clarity_in_1_second": _clamp(item.get("clarity_in_1_second")),
            "specificity": _clamp(item.get("specificity")),
            "spoiler_risk": _clamp(item.get("spoiler_risk")),
            "ctr_potential": _clamp(item.get("ctr_potential")),
        }
        s["ctr_total"] = round(
            s["content_accuracy"] * 0.20 + s["curiosity"] * 0.25 +
            s["clarity_in_1_second"] * 0.20 + s["specificity"] * 0.15 +
            s["spoiler_risk"] * 0.05 + s["ctr_potential"] * 0.15, 3
        )
        scored.append(s)
    if len(scored) < 3:
        return _heuristic_scores(hooks), "score_too_few"
    return scored, None


def _clamp(v) -> float:
    try:
        x = float(v)
    except Exception:
        return 5.0
    return max(0.0, min(10.0, round(x, 2)))


def _heuristic_scores(hooks: list[str]) -> list[dict]:
    out = []
    for i, h in enumerate(hooks):
        # First heuristic hook (from conflict) gets higher specificity.
        spec = 8.0 - min(4.0, i * 0.8)
        s = {
            "hook": h,
            "content_accuracy": max(5.0, 9.0 - i * 0.6),
            "curiosity": 7.0,
            "clarity_in_1_second": 8.0,
            "specificity": spec,
            "spoiler_risk": 9.0,
            "ctr_potential": 7.5 - min(2.0, i * 0.4),
        }
        s["ctr_total"] = round(
            s["content_accuracy"] * 0.20 + s["curiosity"] * 0.25 +
            s["clarity_in_1_second"] * 0.20 + s["specificity"] * 0.15 +
            s["spoiler_risk"] * 0.05 + s["ctr_potential"] * 0.15, 3
        )
        out.append(s)
    return out


def select_hook(scored: list[dict], story: dict) -> dict:
    ranked = sorted(scored, key=lambda s: s.get("ctr_total", 0), reverse=True)
    top = ranked[:5] if ranked else []
    chosen = None
    reason = ""
    for cand in top:
        h = cand["hook"]
        # Reject generic / too-long / suspicious.
        if h.lower() in GENERIC_HOOKS:
            continue
        if len(h.split()) > 8 or len(h) > 48:
            continue
        chosen = cand
        reason = f"Top-{ranked.index(cand)+1} theo ctr_total={cand['ctr_total']}; " \
                 f"curiosity={cand['curiosity']}, clarity={cand['clarity_in_1_second']}, " \
                 f"specificity={cand['specificity']}, spoiler_risk={cand['spoiler_risk']}."
        break
    if chosen is None and ranked:
        chosen = ranked[0]
        reason = "Không có hook nào trong top-5 thỏa tiêu chí; lấy điểm cao nhất làm dự phòng."
    if chosen is None:
        # Last resort: heuristic hook from story, NOT choose_title().
        hook = _heuristic_hooks(story)[0]
        chosen = {
            "hook": hook, "content_accuracy": 6.0, "curiosity": 6.0,
            "clarity_in_1_second": 7.0, "specificity": 5.0,
            "spoiler_risk": 9.0, "ctr_potential": 6.0, "ctr_total": 6.2,
        }
        reason = "Không có hook hợp lệ; sinh hook heuristic từ story summary (không dùng keyword table cũ)."
    return {
        "hook": chosen["hook"],
        "reason": reason,
        "rank": ranked.index(chosen) + 1 if chosen in ranked else 0,
        "scores": chosen,
        "selected_angle": (story.get("clickable_angles") or ["khoảnh khắc kịch tính"])[0],
    }


def refine_hook(output_dir: Path, reference_visual_analysis: dict | None = None) -> dict:
    """Refine pass sau khi có reference visual: regenerate hook ngắn informed bởi visual.

    Đọc reference_visual_analysis.json (hoặc thumbnail_vision_analysis.json alias).
    Trả dict {hook, selected_angle, refined_from, seed_hook, reason, fallback_reason}.
    Fail-open: nếu refine fail -> trả seed hook hiện tại (đọc thumbnail_hook_selected.json).
    Chỉ override seed hook khi hook mới rõ ràng không nhạt (có chứa keyword visual/subject).
    """
    out = Path(output_dir)
    sel_path = out / "thumbnail_hook_selected.json"
    seed = {}
    if sel_path.exists():
        try:
            seed = json.loads(sel_path.read_text(encoding="utf-8"))
        except Exception:
            seed = {}
    seed_hook = (seed.get("hook") or "").strip()
    seed_angle = (seed.get("selected_angle") or "").strip()

    # Đọc visual analysis (alias hoặc gốc).
    vis = reference_visual_analysis or {}
    if not vis:
        for p in (out / "reference_visual_analysis.json", out / "thumbnail_vision_analysis.json"):
            if p.exists():
                try:
                    vis = json.loads(p.read_text(encoding="utf-8"))
                    break
                except Exception:
                    pass
    if not vis:
        return {"hook": seed_hook, "selected_angle": seed_angle,
                "refined_from": "visual", "seed_hook": seed_hook,
                "reason": "no_visual_analysis_keep_seed", "fallback_reason": "no_visual_analysis"}

    # Story gốc để giữ context.
    story = {}
    sp = out / "thumbnail_story_analysis.json"
    if sp.exists():
        try:
            story = json.loads(sp.read_text(encoding="utf-8"))
        except Exception:
            pass

    subject = (vis.get("main_subjects") or [vis.get("main_subject") or ""])
    subject_str = ", ".join(s for s in (subject if isinstance(subject, list) else [subject]) if s)[:120]
    emotion = vis.get("expression") or story.get("strongest_emotion") or ""
    empty = vis.get("recommended_text_regions") or vis.get("empty_areas") or []
    empty_str = (", ".join(empty) if isinstance(empty, list) else str(empty))[:80]

    prompt = f"""Bạn đang chọn lại hook (tiêu đề ngắn 2-6 từ) cho thumbnail YouTube Việt, BIẾT rõ ảnh reference đã chọn.

Ảnh reference mô tả:
- Chủ thể chính: {subject_str or 'nhân vật kịch tính'}
- Cảm xúc/biểu cảm: {emotion or 'kịch tính, căng thẳng'}
- Vùng trống nên để chữ: {empty_str or 'phía trên hoặc dưới'}

Story: {(story.get('core_plot') or '')[:400]} | Xung đột: {(story.get('main_conflict') or '')[:200]}

Hook seed hiện tại (có thể generic): {seed_hook or 'TRẢ THÙ'}

Yêu cầu: sinh 6 hook tiếng Việt 2-6 từ, MỚI, cụ thể hơn seed, gắn với chủ thể/biểu cảm thật của ảnh.
- Tránh hook nhạt kiểu tên file ("VIDEO 1", "TẬP MỚI").
- Giữ gây tò mò, không spoil twist chính.
- Viết hoa, không dấu câu.

Trả JSON: {{"hooks":["...","..."]}}
"""
    content, err = chat(CREATIVE_MODEL, [
        {"role": "system", "content": "Bạn biên tập hook thumbnail Việt ngắn gọn, gây tò mò. Trả JSON hợp lệ."},
        {"role": "user", "content": prompt},
    ], 0.5)
    if err or not content:
        return {"hook": seed_hook, "selected_angle": seed_angle,
                "refined_from": "visual", "seed_hook": seed_hook,
                "reason": f"refine_chat_failed_keep_seed: {err}", "fallback_reason": err or "refine_fail"}

    try:
        data = json.loads(_extract_json_block(content))
        hooks = [h.strip() for h in (data.get("hooks") or []) if h.strip()]
    except Exception:
        hooks = []
    if not hooks:
        return {"hook": seed_hook, "selected_angle": seed_angle,
                "refined_from": "visual", "seed_hook": seed_hook,
                "reason": "refine_no_hooks_keep_seed", "fallback_reason": "refine_no_hooks"}

    # Score heuristic ngắn: ưu tiên hook có keyword visual/subject + độ dài vừa.
    vis_kw = [w.lower() for w in (str(subject_str) + " " + str(emotion)).split() if len(w) >= 3]
    def _score(h):
        low = h.lower()
        s = 5.0
        if any(k in low for k in vis_kw):
            s += 2.0
        nw = len(h.split())
        if 2 <= nw <= 5:
            s += 1.5
        if 4 <= len(h) <= 30:
            s += 1.0
        if h.lower() in GENERIC_HOOKS:
            s -= 3.0
        return s
    scored = sorted(hooks, key=_score, reverse=True)
    best = scored[0]
    # Chỉ override nếu best tốt hơn seed một cách rõ ràng (score >= 7 và khác seed).
    if _score(best) >= 7.0 and best.upper() != seed_hook.upper():
        refined = {
            "hook": best, "selected_angle": seed_angle or "khoảnh khắc kịch tính",
            "reason": f"refined_from_visual (score={_score(best):.1f}); visual subject={subject_str[:40]}",
            "rank": 1, "scores": {"ctr_total": round(_score(best), 2)},
            "refined_from": "visual", "seed_hook": seed_hook,
        }
        sel_path.write_text(json.dumps(refined, ensure_ascii=False, indent=2), encoding="utf-8")
        return refined
    return {"hook": seed_hook, "selected_angle": seed_angle,
            "refined_from": "visual", "seed_hook": seed_hook,
            "reason": f"refine_not_better_keep_seed (best={best} score={_score(best):.1f})",
            "fallback_reason": ""}


def run(output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    corpus = gather_corpus(output_dir)
    story, story_err = analyze_story(corpus)
    (output_dir / "thumbnail_story_analysis.json").write_text(
        json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")

    hooks, hook_err = ideate_hooks(story)
    (output_dir / "thumbnail_hook_candidates.json").write_text(
        json.dumps({"hooks": hooks, "fallback_reason": hook_err, "count": len(hooks)},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    scored, score_err = score_hooks(hooks, story)
    (output_dir / "thumbnail_hook_scores.json").write_text(
        json.dumps({"scores": scored, "fallback_reason": score_err},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    selected = select_hook(scored, story)
    (output_dir / "thumbnail_hook_selected.json").write_text(
        json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8")

    fallback_reason = None
    if story.get("status") != "ok":
        fallback_reason = story.get("fallback_reason") or "story_fallback"
    elif hook_err:
        fallback_reason = hook_err
    elif score_err:
        fallback_reason = score_err

    result = {
        "story_analysis": story,
        "hook": selected["hook"],
        "selected_angle": selected["selected_angle"],
        "fallback_reason": fallback_reason,
        "model": CREATIVE_MODEL,
        "elapsed_seconds": round(time.time() - started, 3),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir")
    parser.add_argument("--refine", action="store_true",
                        help="Chỉ chạy refine pass (visual-aware), không chạy seed story/hook đầy đủ.")
    args = parser.parse_args()
    if args.refine:
        try:
            result = refine_hook(Path(args.output_dir))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        except Exception as exc:  # noqa: BLE001
            log(f"FATAL refine: {exc}")
            return 0  # fail-open: giữ seed
    try:
        result = run(Path(args.output_dir))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001
        log(f"FATAL: {exc}")
        # Fail-open: write minimal artifacts so caller can proceed.
        out = Path(args.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        if not (out / "thumbnail_story_analysis.json").exists():
            (out / "thumbnail_story_analysis.json").write_text(
                json.dumps(heuristic_story(gather_corpus(out), f"fatal: {exc}"),
                           ensure_ascii=False, indent=2), encoding="utf-8")
        if not (out / "thumbnail_hook_selected.json").exists():
            sel = {"hook": "KHOẢNH KHẮC KỊCH TÍNH", "reason": f"fatal: {exc}",
                   "rank": 0, "scores": {}, "selected_angle": "khoảnh khắc kịch tính"}
            (out / "thumbnail_hook_selected.json").write_text(
                json.dumps(sel, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if FAIL_OPEN else 1


if __name__ == "__main__":
    raise SystemExit(main())