#!/usr/bin/env python3
import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

from dialogue_boundary import boundary_after
from structured_json import extract_first_json_object
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tts_voice_quality import normalize_spoken_text, text_quality_issues


def env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except Exception:
        return float(default)


def env_int(name, default):
    try:
        return int(float(os.environ.get(name, default)))
    except Exception:
        return int(default)


def translate_batch_size_for_provider(api_provider):
    """Use a smaller default for Ollama while retaining the env override."""
    default = 10 if api_provider == "ollama" else 20
    return max(1, env_int("OPTIMIZER_TRANSLATE_BATCH_SIZE", default))


# balanced_dub mặc định: optimizer rút dub_text trước, TTS fit bằng speed bounded sau.
# Chỉ SYNC_MODE=aggressive_legacy + ALLOW_AGGRESSIVE_ATEMPO=1 mới giữ frame_strict cũ.
_VIET_DUB_SYNC_POLICY = (os.environ.get("TTS_SYNC_POLICY", "bounded") or "bounded").strip().lower()
_FRAME_STRICT = _VIET_DUB_SYNC_POLICY == "frame_strict"
_ALLOW_AGGRESSIVE_ATEMPO = (os.environ.get("ALLOW_AGGRESSIVE_ATEMPO", "0") or "0").strip().lower() in {"1", "true", "yes", "on"}
_OPT_MAX_SPEED = 50.0 if (_FRAME_STRICT and _ALLOW_AGGRESSIVE_ATEMPO) else env_float("MAX_TTS_SPEED", env_float("HARD_MAX_SPEED", 1.50))
_SUB_ONLY_CEILING = env_float("SUBTITLE_ONLY_IF_RATIO_ABOVE", 10.0 if (_FRAME_STRICT and _ALLOW_AGGRESSIVE_ATEMPO) else 2.0)

CONFIG = {
    "enabled": os.environ.get("VIET_DUB_TIMING_OPTIMIZER", "1") != "0",
    "target_max_speed": env_float("TARGET_MAX_SPEED", 1.25),
    "soft_max_speed": env_float("SOFT_MAX_SPEED", 1.35),
    "hard_max_speed": env_float("HARD_MAX_SPEED", 1.50),
    "hard_max_duration": env_float("HARD_MAX_DURATION", 3.0),
    "max_tts_speed": _OPT_MAX_SPEED,
    "rewrite_if_ratio_above": env_float("REWRITE_IF_RATIO_ABOVE", env_float("TARGET_MAX_SPEED", 1.25)),
    "subtitle_only_if_ratio_above": _SUB_ONLY_CEILING,
    "max_rewrite_attempts": env_int("MAX_REWRITE_ATTEMPTS", 3),
    "min_segment_duration": env_float("MIN_SEGMENT_DURATION", 1.6),
    "merge_gap_under": env_float("MERGE_GAP_UNDER", 0.65),
    "allow_audio_overhang": env_float("ALLOW_AUDIO_OVERHANG", 0.6),
    "max_start_drift": env_float("MAX_START_DRIFT", 0.12),
    "meaning_check_enabled": os.environ.get("MEANING_CHECK_ENABLED", "1") != "0",
    "unsafe_rewrite_fallback": os.environ.get("UNSAFE_REWRITE_FALLBACK", "subtitle_only"),
    "original_volume_when_dub": env_float("ORIGINAL_VOLUME_WHEN_DUB", 0.15),
    "original_volume_when_subtitle_only": env_float("ORIGINAL_VOLUME_WHEN_SUBTITLE_ONLY", 0.6),
    "tts_timeout_seconds": env_int("EDGE_TTS_TIMEOUT_SECONDS", 20),
    "translate_batch_size": env_int("OPTIMIZER_TRANSLATE_BATCH_SIZE", 20),
    "translate_min_batch_size": env_int("OPTIMIZER_TRANSLATE_MIN_BATCH_SIZE", 1),
    "ollama_num_predict": env_int("OLLAMA_NUM_PREDICT", 4096),
    # Timeout chat API: ngắn hơn để tránh kẹt lâu khi 9router chậm; fallback khi timeout.
    "chat_timeout_seconds": env_int("OPTIMIZER_CHAT_TIMEOUT_SECONDS", 90),
    "batch_timeout_seconds": env_int("OPTIMIZER_BATCH_TIMEOUT_SECONDS", 180),
    "progress_file": os.environ.get("OPTIMIZER_PROGRESS_FILE", ""),
    "translation_memory_max_chars": env_int("TRANSLATION_MEMORY_MAX_CHARS", 6000),
    # A model occasionally returns the original Chinese despite a successful JSON response.
    # One strict retry per group is enough to correct a formatting lapse; never loop forever.
    "translation_quality_retries": max(0, env_int("OPTIMIZER_TRANSLATION_QUALITY_RETRIES", env_int("OPTIMIZER_TRANSLATION_CJK_RETRIES", 1))),
    # Dub grouping chặt: bám từng cue, chỉ gộp cue cực ngắn để TTS không vụn.
    # Cho phép gộp tối đa 3 cue / group (case Douyin 163 cue ASR có nhiều slot 0.8-1.2s)
    # nhưng group không dài quá 4.5s -> TTS tự nhiên hơn mà không tạo cue dài kiểu 20s.
    "dub_max_group_cues": env_int("DUB_MAX_GROUP_CUES", 3),
    "dub_merge_max_duration": env_float("DUB_MERGE_MAX_DURATION_SECONDS", 4.5),
    # Canonical normal DUB_GATE floor from run.sh.  A source cue already above
    # the short-group duration cap must not activate the 0.65 relaxation.
    "dub_gate_min_ratio": env_float("DUB_GATE_MIN_RATIO", 0.75),
    # Keep optimizer output above run.sh's safe short-group DUB_GATE floor without
    # importing shell configuration.  This is deliberately the same env/default.
    "dub_short_group_min_ratio": env_float("DUB_GATE_SHORT_GROUP_MIN_RATIO", 0.65),
}

CJK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
REVIEW_FILM_STYLE_RULE = (
    "Dùng văn phong review phim tự nhiên; giữ tên riêng, vai vế và đại từ nhất quán; "
    "không thêm tình tiết không có trong nguồn."
)


def validate_vietnamese_translation(subtitle_per_cue, dub_text):
    """Reject malformed Vietnamese before it can reach TTS."""
    texts = [normalize_spoken_text(dub_text)]
    texts.extend(normalize_spoken_text(item.get("subtitle_text")) for item in subtitle_per_cue)
    if not texts[0] or any(not text for text in texts[1:]):
        raise RuntimeError("translation_empty")
    for text in texts:
        issues = text_quality_issues(text)
        if issues:
            raise RuntimeError(f"translation_{issues[0]}")


def load_translation_memory_context(path, max_chars=None):
    if not path:
        return ""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except FileNotFoundError:
        return ""
    except Exception as exc:
        print(f"WARN: Không đọc được translation memory context: {exc}", file=sys.stderr, flush=True)
        return ""
    limit = int(max_chars if max_chars is not None else CONFIG["translation_memory_max_chars"])
    if limit > 0 and len(text) > limit:
        text = text[:limit].rstrip() + "\n[Memory trimmed to fit prompt budget]"
    return text


def translation_memory_prompt_block(context):
    context = (context or "").strip()
    if not context:
        return ""
    return f"""

BỘ NHỚ DỊCH ÁP DỤNG CHO VIDEO NÀY:
{context}

Quy tắc dùng bộ nhớ:
- Chỉ dùng bộ nhớ để chọn văn phong, thuật ngữ, tên riêng và xưng hô.
- Không để bộ nhớ làm sai nghĩa câu Trung hiện tại.
- Không phá format JSON, timing, subtitle_segments hoặc dub_text.
"""


def parse_ms(ts):
    hh, mm, rest = ts.split(":")
    ss, ms = rest.split(",")
    return ((int(hh) * 60 + int(mm)) * 60 + int(ss)) * 1000 + int(ms)


def fmt_ms(ms):
    ms = max(0, int(round(ms)))
    hh, rem = divmod(ms, 3600000)
    mm, rem = divmod(rem, 60000)
    ss, mmm = divmod(rem, 1000)
    return f"{hh:02d}:{mm:02d}:{ss:02d},{mmm:03d}"


def parse_srt(path):
    content = Path(path).read_text(encoding="utf-8", errors="replace").strip()
    entries = []
    if not content:
        return entries
    for block in re.split(r"\n\s*\n", content):
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        try:
            idx = int(re.sub(r"\D", "", lines[0]) or len(entries) + 1)
            start_raw, end_raw = [part.strip() for part in lines[1].split("-->", 1)]
            text = re.sub(r"<[^>]+>", "", " ".join(lines[2:]).strip())
            entries.append({"id": idx, "start_ms": parse_ms(start_raw), "end_ms": parse_ms(end_raw), "source_text": text})
        except Exception:
            continue
    return entries


def write_srt(path, entries, text_key, skip_subtitle_only=False):
    out = []
    n = 1
    for item in entries:
        if skip_subtitle_only and item.get("mode") == "subtitle_only":
            continue
        text = (item.get(text_key) or "").strip()
        if not text:
            continue
        out.append(str(n))
        out.append(f"{fmt_ms(item['start_ms'])} --> {fmt_ms(item['end_ms'])}")
        out.append(text)
        out.append("")
        n += 1
    Path(path).write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def chat(api_base, api_key, model, messages, temperature=0.2, timeout=None, api_provider="ninerouter"):
    if timeout is None:
        timeout = CONFIG["chat_timeout_seconds"]
    if api_provider == "ollama":
        payload = {
            "model": model,
            "messages": messages,
            "format": "json",
            "temperature": temperature,
            "stream": False,
            "think": False,
            "options": {
                "temperature": temperature,
                "num_predict": CONFIG["ollama_num_predict"],
            },
        }
        url = api_base.rstrip("/") + "/api/chat"
        headers = {"Content-Type": "application/json"}
        content_key = "ollama"
    else:
        payload = {"model": model, "messages": messages, "temperature": temperature, "stream": False, "think": False}
        url = api_base.rstrip("/") + "/chat/completions"
        headers = {"Authorization": "Bearer " + api_key, "Content-Type": "application/json"}
        content_key = "ninerouter"

    # 429 backoff: retry vài lần với sleep tăng dần để tránh biến rate-limit thành fail hàng loạt.
    max_retries = env_int("OPTIMIZER_CHAT_MAX_RETRIES", 3)
    backoff_base = env_float("OPTIMIZER_CHAT_BACKOFF_BASE", 5.0)
    last_exc = None
    for attempt in range(max_retries + 1):
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_exc = exc
            body = ""
            try:
                body = exc.read().decode("utf-8", "replace")[:200]
            except Exception:
                pass
            if exc.code == 429 and attempt < max_retries:
                sleep_s = backoff_base * (2 ** attempt)  # 5, 10, 20 ...
                log_progress(f"chat 429 Too Many Requests; backoff {sleep_s:.0f}s (attempt {attempt+1}/{max_retries}): {body}")
                time.sleep(sleep_s)
                continue
            raise RuntimeError(f"HTTP {exc.code}: {body or exc.reason}")
        except urllib.error.URLError as exc:
            last_exc = exc
            if attempt < max_retries:
                sleep_s = backoff_base * (2 ** attempt)
                log_progress(f"chat network error; backoff {sleep_s:.0f}s (attempt {attempt+1}/{max_retries}): {exc}")
                time.sleep(sleep_s)
                continue
            raise RuntimeError(f"network: {exc}")
        # success
        if content_key == "ollama":
            content = data.get("message", {}).get("content", "").strip()
            if not content:
                compatibility_payload = dict(payload)
                compatibility_payload.pop("format", None)
                compatibility_req = urllib.request.Request(
                    url,
                    data=json.dumps(compatibility_payload, ensure_ascii=False).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(compatibility_req, timeout=timeout) as compatibility_resp:
                        compatibility_data = json.loads(compatibility_resp.read().decode("utf-8"))
                except urllib.error.HTTPError as exc:
                    raise RuntimeError(f"Ollama compatibility retry HTTP {exc.code}") from exc
                except urllib.error.URLError as exc:
                    raise RuntimeError("Ollama compatibility retry network failure") from exc
                content = compatibility_data.get("message", {}).get("content", "").strip()
                if not content:
                    raise RuntimeError("Ollama không trả nội dung")
            return content
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        if not content:
            raise RuntimeError("9Router không trả nội dung")
        return content
    raise RuntimeError(f"chat exhausted retries: {last_exc}")


def log_progress(message):
    print(f"Optimizer progress: {message}", flush=True)


def write_progress(phase, group_index=None, total_groups=None, last_action=None, extra=None):
    """Ghi file progress JSON nhẹ để dashboard/tool ngoài theo dõi (không raise)."""
    path = CONFIG.get("progress_file") or ""
    if not path:
        return
    try:
        payload = {
            "phase": phase,
            "group_index": group_index,
            "total_groups": total_groups,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "last_action": last_action,
        }
        if isinstance(extra, dict):
            payload.update(extra)
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def extract_json(text):
    return extract_first_json_object(text)


def group_entries(entries):
    groups = []
    i = 0
    while i < len(entries):
        group = [entries[i]]
        while i + 1 < len(entries):
            duration = (group[-1]["end_ms"] - group[0]["start_ms"]) / 1000
            gap = (entries[i + 1]["start_ms"] - group[-1]["end_ms"]) / 1000
            current_text = " ".join(item["source_text"] for item in group).strip()
            next_text = entries[i + 1]["source_text"].strip()
            phrase_open = not re.search(r"[。！？!?；;：:]$", current_text)
            next_is_continuation = bool(next_text) and gap <= CONFIG["merge_gap_under"]
            if (duration < CONFIG["min_segment_duration"] or phrase_open) and next_is_continuation:
                i += 1
                group.append(entries[i])
            else:
                break
        groups.append(group)
        i += 1
    return groups


def group_entries_for_dub(entries, with_report=False):
    """Group chặt cho dub.srt/TTS: bám từng cue, KHÔNG merge dây chuyền dài.

    Chỉ gộp cue kế khi:
    - cue hiện < min_segment_duration (cực ngắn, TTS đọc 1 câu ~1s dễ khấp/vụn),
    - gap <= merge_gap_under,
    - group chưa đạt DUB_MAX_GROUP_CUES (mặc định 3),
    - group_duration + cue kế <= DUB_MERGE_MAX_DURATION_SECONDS (mặc định 4.5s).
    Vòng lặp trong gộp tới khi chạm max_cues/max_dur/gap lớn -> không có group dài 20-28s
    như group_entries cũ (max_dur 4.5s là cứng).
    """
    max_cues = max(1, int(CONFIG["dub_max_group_cues"]))
    max_dur = float(CONFIG["dub_merge_max_duration"])
    min_dur = float(CONFIG["min_segment_duration"])
    merge_gap = float(CONFIG["merge_gap_under"])
    groups = []
    i = 0
    while i < len(entries):
        group = [entries[i]]
        # Gộp cue kế liên tiếp khi group vẫn cực ngắn, đủ slot, gap nhỏ, chưa chạm max_cues.
        while (i + 1 < len(entries) and len(group) < max_cues):
            cur_dur = (group[-1]["end_ms"] - group[0]["start_ms"]) / 1000
            if cur_dur >= min_dur:
                break
            gap = (entries[i + 1]["start_ms"] - group[-1]["end_ms"]) / 1000
            next_dur = (entries[i + 1]["end_ms"] - group[0]["start_ms"]) / 1000
            boundary_reason = boundary_after(group[-1].get("source_text"))
            if boundary_reason:
                break
            if gap <= merge_gap and next_dur <= max_dur:
                i += 1
                group.append(entries[i])
            else:
                break
        groups.append(group)
        i += 1

    # DUB_GATE runs before TTS.  A dense episode can otherwise be safely bounded
    # (<=3 cues / <=4.5s) yet fall just below its short-group cue-count floor.
    # Split only the minimum number of existing merges needed to satisfy that
    # floor, so translation/TTS retain as many natural short-cue merges as safe.
    has_long_original_cue = any(
        (entry["end_ms"] - entry["start_ms"]) / 1000.0 > max_dur
        for entry in entries
    )
    floor_ratio = (
        CONFIG["dub_gate_min_ratio"] if has_long_original_cue
        else CONFIG["dub_short_group_min_ratio"]
    )
    minimum_groups = max(0, min(len(entries), math.ceil(len(entries) * min(1.0, max(0.0, float(floor_ratio))))))
    while len(groups) < minimum_groups:
        candidates = []
        for group_index, group in enumerate(groups):
            if len(group) < 2:
                continue
            for split_index in range(1, len(group)):
                previous_text = str(group[split_index - 1].get("source_text") or "").strip()
                semantic_boundary = bool(boundary_after(previous_text))
                duration = max(0, group[-1]["end_ms"] - group[0]["start_ms"])
                compression = len(group) / max(1, duration)
                # Prefer punctuation/semantic boundaries, then groups with more
                # cues and greater density/duration; stable indices break ties.
                candidates.append((
                    not semantic_boundary, -len(group), -compression, -duration,
                    group_index, split_index,
                ))
        if not candidates:
            break
        _, _, _, _, group_index, split_index = min(candidates)
        group = groups[group_index]
        groups[group_index:group_index + 1] = [group[:split_index], group[split_index:]]
    if not with_report:
        return groups
    boundary_report = []
    for group_index, group in enumerate(groups):
        if group_index >= len(groups) - 1:
            continue
        reason = boundary_after(group[-1].get("source_text"))
        if reason:
            boundary_report.append({
                "source_cue_ids": [item.get("id") for item in group],
                "boundary_reason": reason,
            })
    return groups, boundary_report


def _group_segments_payload(group):
    """Build per-cue segment list for one group (gửi cho model để dịch từng cue)."""
    return [
        {
            "id": int(item["id"]),
            "start_ms": int(item["start_ms"]),
            "end_ms": int(item["end_ms"]),
            "source_text": item["source_text"],
        }
        for item in group
    ]


def build_subtitle_per_cue(group, subtitle_segments, fallback_text, warnings=None, group_index=None):
    """Map bản dịch theo từng cue gốc của group.

    subtitle_segments: list {"id":..,"text":..} do model trả (id khớp segment id).
    Nếu thiếu id / rỗng -> dùng distribute_text(fallback_text, group) chia theo tỷ lệ độ dài source,
    đồng thời ghi warning subtitle_segments_missing_fallback_distribute.
    Trả list [{id,start_ms,end_ms,subtitle_text}] đúng theo timestamp cue gốc.
    """
    by_id = {}
    if isinstance(subtitle_segments, list):
        for seg in subtitle_segments:
            if not isinstance(seg, dict):
                continue
            try:
                sid = int(seg.get("id"))
            except Exception:
                continue
            text = str(seg.get("text") or "").strip()
            if text:
                by_id[sid] = text

    texts = []
    missing_ids = []
    for item in group:
        sid = int(item["id"])
        text = by_id.get(sid)
        if text:
            texts.append(text)
        else:
            texts.append(None)
            missing_ids.append(sid)

    n_none = sum(1 for t in texts if t is None)
    if n_none > 0:
        fallback = (fallback_text or "").strip()
        distributed = distribute_text(fallback, group) if fallback else ["" for _ in group]
        for i, t in enumerate(texts):
            if t is None:
                texts[i] = (distributed[i] if i < len(distributed) else "").strip()
        if warnings is not None:
            warnings.append({
                "reason": "subtitle_segments_missing_fallback_distribute",
                "group_index": group_index,
                "missing_ids": missing_ids,
            })

    return [
        {
            "id": int(item["id"]),
            "start_ms": int(item["start_ms"]),
            "end_ms": int(item["end_ms"]),
            "subtitle_text": (texts[i] or "").strip(),
        }
        for i, item in enumerate(group)
    ]


def translate_group(group, api_base, api_key, model, api_provider="ninerouter", translation_memory_context=""):
    source_text = " ".join(item["source_text"] for item in group).strip()
    duration = max(0.1, (group[-1]["end_ms"] - group[0]["start_ms"]) / 1000)
    segments = _group_segments_payload(group)
    prompt = f"""Dịch câu tiếng Trung sang tiếng Việt để dùng cho phụ đề và lồng tiếng video ngắn.

Yêu cầu:
- subtitle_segments: list bản Việt cho TỪNG cue gốc (id khớp), đủ ý để hiện phụ đề, bám đúng từng khung thời gian.
- dub_text: bản gộp ngắn hơn, tự nhiên, dễ nghe, phù hợp lồng tiếng trong khoảng {duration:.2f} giây.
- Không dịch sát chữ nếu làm câu dài khó nghe.
- Giữ ý chính và cảm xúc chính.
- Bỏ từ đệm, rút gọn chi tiết phụ nếu cần.
- Không thêm ý mới, không đổi nghĩa gốc.
- Trả về JSON duy nhất dạng: {{"subtitle_segments":[{{"id":1,"text":"..."}}],"dub_text":"..."}}
{translation_memory_prompt_block(translation_memory_context)}

Câu Trung (segments):
{json.dumps(segments, ensure_ascii=False)}"""
    prompt += "\n- " + REVIEW_FILM_STYLE_RULE
    last_error = None
    for attempt in range(CONFIG["translation_quality_retries"] + 1):
        strict = "\nBẮT BUỘC: CHỈ tiếng Việt; không được chứa bất kỳ ký tự Trung/CJK nào trong subtitle_segments hoặc dub_text." if attempt else ""
        content = chat(
            api_base,
            api_key,
            model,
            [
                {"role": "system", "content": "Bạn dịch và biên tập lời thoại Việt cho lồng tiếng video ngắn. Luôn trả JSON hợp lệ, subtitle_segments phải có đủ số item bằng số segment input." + strict},
                {"role": "user", "content": prompt + strict},
            ],
            api_provider=api_provider,
        )
        data = extract_json(content)
        subtitle_segments = data.get("subtitle_segments") or []
        dub_text = str(data.get("dub_text") or "").strip()
        # Compatibility fallback is permitted only from model output, never source Chinese.
        fallback_subtitle = str(data.get("subtitle_text") or "").strip()
        if not dub_text:
            dub_text = fallback_subtitle
        if not fallback_subtitle:
            fallback_subtitle = dub_text
        subtitle_per_cue = build_subtitle_per_cue(group, subtitle_segments, fallback_subtitle)
        try:
            validate_vietnamese_translation(subtitle_per_cue, dub_text)
            return subtitle_per_cue, dub_text
        except RuntimeError as exc:
            last_error = exc
            if attempt >= CONFIG["translation_quality_retries"]:
                raise
    raise last_error or RuntimeError("translation_failed")


def translate_groups_batch(group_payloads, api_base, api_key, model, api_provider="ninerouter", warnings=None, translation_memory_context=""):
    expected_ids = {int(payload["group_id"]) for payload in group_payloads}
    prompt_items = []
    for payload in group_payloads:
        prompt_items.append({
            "group_id": payload["group_id"],
            "duration_seconds": round(payload["duration"], 2),
            "source_text": payload["source_text"],
            "segments": payload["segments"],
        })
    prompt = """Dịch các câu tiếng Trung sang tiếng Việt để dùng cho phụ đề và lồng tiếng video ngắn.

Yêu cầu cho từng item:
- subtitle_segments: list bản Việt cho TỪNG cue gốc (id khớp id trong segments), đủ ý để hiện phụ đề, bám từng khung thời gian.
- dub_text: bản gộp ngắn hơn, tự nhiên, dễ nghe, phù hợp lồng tiếng trong duration_seconds.
- subtitle_segments phải có đủ item bằng số segment trong input.
- Không dịch sát chữ nếu làm câu dài khó nghe.
- Giữ ý chính và cảm xúc chính.
- Bỏ từ đệm, rút gọn chi tiết phụ nếu cần.
- Không thêm ý mới, không đổi nghĩa gốc.
""" + translation_memory_prompt_block(translation_memory_context) + """

Trả về JSON duy nhất dạng:
{"items":[{"group_id":1,"subtitle_segments":[{"id":1,"text":"..."}],"dub_text":"..."}]}

Input:
""" + json.dumps({"items": prompt_items}, ensure_ascii=False)
    prompt += "\n- " + REVIEW_FILM_STYLE_RULE
    content = chat(
        api_base,
        api_key,
        model,
        [
            {"role": "system", "content": "Bạn dịch và biên tập lời thoại Việt cho lồng tiếng video ngắn. Luôn trả JSON hợp lệ, subtitle_segments phải đủ số item bằng số segment input."},
            {"role": "user", "content": prompt},
        ],
        timeout=CONFIG["batch_timeout_seconds"],
        api_provider=api_provider,
    )
    data = extract_json(content)
    result = {}
    # Map group payload by id để lấy group gốc khi build per-cue.
    payload_by_id = {int(p["group_id"]): p for p in group_payloads}
    for item in data.get("items", []):
        try:
            group_id = int(item.get("group_id"))
        except Exception:
            continue
        payload = payload_by_id.get(group_id)
        if not payload:
            continue
        subtitle_segments = item.get("subtitle_segments") or []
        dub_text = str(item.get("dub_text") or "").strip()
        fallback_subtitle = str(item.get("subtitle_text") or "").strip()
        if not dub_text:
            dub_text = fallback_subtitle
        if not fallback_subtitle:
            fallback_subtitle = dub_text
        subtitle_per_cue = build_subtitle_per_cue(
            payload["group"], subtitle_segments, fallback_subtitle,
            warnings=warnings, group_index=group_id,
        )
        validate_vietnamese_translation(subtitle_per_cue, dub_text)
        # Chỉ tính là có kết quả khi có dub_text (subtitle có thể rỗng → fallback distribute).
        if dub_text:
            result[group_id] = (subtitle_per_cue, dub_text)
    missing = sorted(expected_ids - set(result))
    if missing:
        raise RuntimeError(
            "batch_translate_missing_items "
            f"expected={len(expected_ids)} got={len(result)} missing={missing[:12]}"
        )
    return result


def translate_groups_adaptive(group_payloads, api_base, api_key, model, min_batch_size=1, warnings=None, depth=0, api_provider="ninerouter", translation_memory_context=""):
    if not group_payloads:
        return {}
    try:
        return translate_groups_batch(
            group_payloads,
            api_base,
            api_key,
            model,
            api_provider=api_provider,
            warnings=warnings,
            translation_memory_context=translation_memory_context,
        )
    except Exception as exc:
        current_size = len(group_payloads)
        if current_size <= max(1, int(min_batch_size)):
            raise
        next_size = current_size // 2 if current_size > 5 else 1
        next_size = max(1, min(current_size - 1, next_size))
        error = str(exc)[:500]
        log_progress(f"batch translate failed size={current_size}; retrying with size={next_size}: {error}")
        if warnings is not None:
            warnings.append({
                "reason": "batch_translate_retry_smaller",
                "batch_size": current_size,
                "retry_batch_size": next_size,
                "error": error,
            })
        result = {}
        for start in range(0, current_size, next_size):
            chunk = group_payloads[start:start + next_size]
            result.update(
                translate_groups_adaptive(
                    chunk,
                    api_base,
                    api_key,
                    model,
                    min_batch_size=min_batch_size,
                    warnings=warnings,
                    depth=depth + 1,
                    api_provider=api_provider,
                    translation_memory_context=translation_memory_context,
                )
            )
        return result


def measure_wav_ms(path):
    with wave.open(str(path), "rb") as wav_f:
        return int(wav_f.getnframes() * 1000 / wav_f.getframerate())


def estimate_duration_ms(text):
    """Ước lượng duration TTS (ms) khi không có edge-tts để probe timing.

    Dựa tốc độ đọc tiếng Việt trung bình ~14 char/s (≈ 71ms/char) cho neural TTS Việt.
    Đây chỉ là probe timing (chỉ tác động tới quyết định speed/rewrite), không phải TTS cuối,
    nên sai số nhỏ không phá pipeline.
    """
    # Đếm ký tự có nghĩa (bỏ whitespace), tối thiểu 1 để không ra 0.
    chars = max(1, len(re.sub(r"\s+", "", text or "")))
    rate_cps = env_float("OPTIMIZER_PROBE_ESTIMATE_CPS", 14.0)
    return int(chars / rate_cps * 1000)


def _edge_tts_available():
    try:
        subprocess.run(["edge-tts", "--list-voices"], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
        return subprocess.run(["command", "-v", "edge-tts"], check=False,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    except Exception:
        return False


def synthesize_measure(text, voice, work_dir, name):
    """Đo duration TTS (ms) của text với voice. Dùng cho timing probe — KHÔNG phải TTS cuối.

    CapCut TTS đã tắt khỏi pipeline. Nếu voice là capcut:* thì fail rõ thay vì
    gọi CapCut wrapper hoặc fallback Edge âm thầm.
    - Resona/Kokoro/AI33: KHÔNG gọi engine thật trong probe (tốn credit/CPU + chậm).
      Dùng char-rate estimate. TTS thật chỉ chạy ở generate_vietnamese_voice.
    - Nếu KHÔNG có binary edge-tts: ước lượng duration theo char/s (không fatal),
      ghi warning tts_probe_estimated_no_edge_tts.
    """
    safe_text = text.strip() or " "
    mp3_path = work_dir / f"{name}.mp3"
    wav_path = work_dir / f"{name}.wav"
    is_capcut = (voice or "").lower().startswith("capcut:")
    if is_capcut:
        raise RuntimeError("CapCut TTS disabled in OpenClaw pipeline; choose resona, nam, nu or vi-vn-*.")
    is_resona = (voice or "").lower().startswith("resona")
    if is_resona:
        # Probe timing bằng ước lượng char-rate, KHÔNG gọi Resona API (tiết kiệm credit).
        log_progress(f"tts_probe_resona_estimate voice={voice} chars={len(safe_text)}")
        return estimate_duration_ms(safe_text)
    is_ai33 = (voice or "").lower().startswith("ai33")
    if is_ai33:
        # Probe timing bằng ước lượng char-rate, KHÔNG gọi AI33 API (tiết kiệm credit).
        log_progress(f"tts_probe_ai33_estimate voice={voice} chars={len(safe_text)}")
        return estimate_duration_ms(safe_text)
    is_kokoro = (voice or "").lower().startswith("kokoro")
    if is_kokoro:
        # Probe timing bằng ước lượng char-rate, KHÔNG load Kokoro model trong optimizer.
        log_progress(f"tts_probe_kokoro_estimate voice={voice} chars={len(safe_text)}")
        return estimate_duration_ms(safe_text)

    # Xác định voice probe + engine.
    probe_voice = voice

    # Nếu không có edge-tts binary: ước lượng, KHÔNG fatal.
    if not _edge_tts_available():
        log_progress(f"tts_probe_estimated_no_edge_tts voice={voice} chars={len(safe_text)}")
        return estimate_duration_ms(safe_text)

    proc = subprocess.run(
        ["edge-tts", "--voice", probe_voice, "--text", safe_text, "--write-media", str(mp3_path)],
        check=False,
        timeout=CONFIG["tts_timeout_seconds"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0 or not mp3_path.exists() or mp3_path.stat().st_size <= 0:
        # edge-tts chạy nhưng fail (rate limit/voice): ước lượng thay vì fatal.
        log_progress(f"tts_probe_edge_failed estimate_fallback: {(proc.stderr or 'edge-tts failed')[:160]}")
        return estimate_duration_ms(safe_text)
    subprocess.run(["ffmpeg", "-y", "-i", str(mp3_path), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav_path)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return measure_wav_ms(wav_path)


def _capcut_synthesize_measure(text, voice, work_dir, name):
    """Gọi CapCut wrapper để synthesize rồi đo duration thật (ms)."""
    skill_dir = Path(os.environ.get("DOUYIN_DUBBER_SKILL_DIR") or Path(__file__).resolve().parent)
    wrapper = Path(os.environ.get("CAPCUT_TTS_WRAPPER") or (skill_dir / "capcut_tts_synthesize.py"))
    voices_json = Path(os.environ.get("CAPCUT_TTS_VOICES_JSON") or (skill_dir / "capcut_voices.json"))
    if not wrapper.exists():
        raise RuntimeError("capcut wrapper missing")
    voice_type = voice.split(":", 1)[1] if ":" in voice else voice
    resource_id = ""
    try:
        import json as _json
        data = _json.loads(voices_json.read_text(encoding="utf-8"))
        # voices_json có thể là list hoặc dict; tìm entry khớp voice_type.
        entries = data if isinstance(data, list) else list(data.values()) if isinstance(data, dict) else []
        for it in entries:
            if isinstance(it, dict) and (it.get("voice_type") == voice_type or it.get("id") == voice_type):
                resource_id = str(it.get("resource_id") or it.get("resourceId") or "")
                break
    except Exception:
        resource_id = ""
    mp3_path = work_dir / f"{name}.mp3"
    wav_path = work_dir / f"{name}.wav"
    total_timeout = env_int("CAPCUT_TTS_TIMEOUT_TOTAL", 45)
    proc = subprocess.run(
        ["python3", str(wrapper), "--text", text, "--voice", voice_type,
         "--resource-id", resource_id or "0", "--rate", "1.0", "--output", str(mp3_path)],
        check=False, timeout=total_timeout, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )
    if proc.returncode != 0 or not mp3_path.exists() or mp3_path.stat().st_size <= 0:
        raise RuntimeError((proc.stderr or "capcut tts failed")[:300])
    subprocess.run(["ffmpeg", "-y", "-i", str(mp3_path), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav_path)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return measure_wav_ms(wav_path)


def meaning_lock(source_text, vi_text, api_base, api_key, model, api_provider="ninerouter"):
    prompt = f"""Hãy phân tích câu Trung gốc và bản dịch tiếng Việt hiện tại.
Tạo danh sách yếu tố bắt buộc phải giữ khi rút gọn câu để lồng tiếng.
Trả về JSON: {{"must_keep":[],"emotion":"","negation_or_assertion":"","important_terms":[]}}

Câu Trung gốc:
{source_text}

Bản Việt hiện tại:
{vi_text}"""
    try:
        return extract_json(chat(api_base, api_key, model, [{"role": "system", "content": "Bạn phân tích ý nghĩa lời thoại và trả JSON hợp lệ."}, {"role": "user", "content": prompt}], api_provider=api_provider))
    except Exception:
        return {"must_keep": [], "emotion": "", "negation_or_assertion": "", "important_terms": []}


def rewrite_dub(source_text, vi_text, duration, lock, api_base, api_key, model, api_provider="ninerouter"):
    prompt = f"""Câu tiếng Việt sau quá dài để lồng tiếng vào video.
Hãy rút gọn câu này để đọc tự nhiên trong {duration:.2f} giây.

Yêu cầu bắt buộc:
- Giữ đúng ý chính, không thêm ý mới, không đổi nghĩa.
- Không đổi cảm xúc gốc.
- Không đổi phủ định thành khẳng định hoặc ngược lại.
- Không bỏ tên riêng, số liệu, địa điểm quan trọng.
- Ngắn hơn bản cũ và nghe tự nhiên như người Việt nói.
- Không giải thích. Trả về duy nhất một câu tiếng Việt.
- Nếu không thể rút gọn an toàn, trả về đúng chuỗi: UNSAFE_TO_REWRITE

Các ý bắt buộc phải giữ:
{json.dumps(lock, ensure_ascii=False)}

Câu Trung gốc:
{source_text}

Câu Việt hiện tại:
{vi_text}"""
    return chat(api_base, api_key, model, [{"role": "system", "content": "Bạn rút gọn lời thoại Việt an toàn cho lồng tiếng."}, {"role": "user", "content": prompt}], api_provider=api_provider).strip().strip('"')


def meaning_check(source_text, subtitle_text, dub_text, api_base, api_key, model, api_provider="ninerouter"):
    if not CONFIG["meaning_check_enabled"]:
        return {"meaning_preserved": True, "risk_level": "low", "lost_details": [], "changed_meaning": [], "recommendation": "use"}
    prompt = f"""So sánh 3 nội dung sau:
1. Câu Trung gốc: {source_text}
2. Bản Việt đầy đủ: {subtitle_text}
3. Bản Việt rút gọn để lồng tiếng: {dub_text}

Đánh giá bản rút gọn có giữ đúng ý không. Trả về JSON:
{{"meaning_preserved":true,"risk_level":"low","lost_details":[],"changed_meaning":[],"recommendation":"use"}}"""
    try:
        data = extract_json(chat(api_base, api_key, model, [{"role": "system", "content": "Bạn kiểm tra bảo toàn ý nghĩa và trả JSON hợp lệ."}, {"role": "user", "content": prompt}], api_provider=api_provider))
    except Exception as exc:
        return {"meaning_preserved": False, "risk_level": "high", "lost_details": [f"meaning_check_error: {exc}"], "changed_meaning": [], "recommendation": "subtitle_only"}
    return data


def distribute_text(text, group):
    if len(group) == 1:
        return [text]
    source_lengths = [max(1, len(item["source_text"])) for item in group]
    total = sum(source_lengths)
    words = text.split()
    if len(words) < len(group):
        return [text if i == 0 else "" for i in range(len(group))]
    parts = []
    cursor = 0
    for i, length in enumerate(source_lengths):
        if i == len(group) - 1:
            part_words = words[cursor:]
        else:
            take = max(1, round(len(words) * length / total))
            remain_groups = len(group) - i - 1
            take = min(take, max(1, len(words) - cursor - remain_groups))
            part_words = words[cursor:cursor + take]
            cursor += take
        parts.append(" ".join(part_words).strip())
    return parts

def should_keep_group_as_one(text, group):
    if len(group) <= 1:
        return True
    if not text.strip():
        return True
    # Không rải chữ qua nhiều timestamp nếu câu không có điểm ngắt tự nhiên;
    # việc rải đều theo số chữ là nguyên nhân làm câu Việt bị nói dở rồi nhảy ý.
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--original-srt", required=True)
    parser.add_argument("--vietnamese-srt", required=True)
    parser.add_argument("--dub-srt", required=True)
    parser.add_argument("--segments-json", required=True)
    parser.add_argument("--report-json", required=True)
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--api-provider", default="ninerouter", choices=["ninerouter", "ollama"])
    parser.add_argument("--model", required=True)
    parser.add_argument("--voice", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--progress-file", default="")
    parser.add_argument("--translation-memory-context", default="")
    args = parser.parse_args()
    if args.progress_file:
        CONFIG["progress_file"] = args.progress_file
    translation_memory_context = load_translation_memory_context(args.translation_memory_context)
    if translation_memory_context:
        log_progress(f"translation memory context loaded chars={len(translation_memory_context)}")

    entries = parse_srt(args.original_srt)
    if not entries:
        raise SystemExit("original.srt không có segment hợp lệ")

    work_dir = Path(args.work_dir) / "optimizer_probe"
    work_dir.mkdir(parents=True, exist_ok=True)
    output_entries = []          # dub entries (1/group) - dùng cho dub.srt + dubbing_segments.json
    subtitle_entries = []        # subtitle entries (1/cue gốc) - dùng cho vietnamese.srt
    warnings = []
    report = {
        "config": CONFIG,
        "total_segments": len(entries),
        "normal_dub_segments": 0,
        "speed_adjusted_segments": 0,
        "rewritten_segments": 0,
        "subtitle_only_segments": 0,
        "unsafe_rewrite_segments": 0,
        "meaning_check_failed_segments": 0,
        "merged_groups": 0,
        "max_speed_used": 1.0,
        "max_start_drift": 0.0,
        "max_end_overhang": 0.0,
        "warnings": warnings,
        "translation_memory_applied": bool(translation_memory_context),
        "translation_memory_chars": len(translation_memory_context),
    }

    groups, boundary_report = group_entries_for_dub(entries, with_report=True)
    report["dub_group_hard_boundaries"] = boundary_report
    translations = {}
    batch_size = translate_batch_size_for_provider(args.api_provider)
    min_batch_size = max(1, env_int("OPTIMIZER_TRANSLATE_MIN_BATCH_SIZE", 1))
    log_progress(f"parsed {len(entries)} segments into {len(groups)} timing groups")
    for batch_start in range(0, len(groups), batch_size):
        batch_payloads = []
        for offset, group in enumerate(groups[batch_start:batch_start + batch_size], batch_start + 1):
            batch_payloads.append({
                "group_id": offset,
                "group": group,
                "source_text": " ".join(item["source_text"] for item in group).strip(),
                "duration": max(0.1, (group[-1]["end_ms"] - group[0]["start_ms"]) / 1000),
                "segments": _group_segments_payload(group),
            })
        try:
            log_progress(f"translating groups {batch_start + 1}-{min(batch_start + batch_size, len(groups))}/{len(groups)}")
            write_progress("translating", group_index=batch_start + 1, total_groups=len(groups), last_action="translate")
            translations.update(
                translate_groups_adaptive(
                    batch_payloads,
                    args.api_base,
                    args.api_key,
                    args.model,
                    min_batch_size=min_batch_size,
                    warnings=warnings,
                    api_provider=args.api_provider,
                    translation_memory_context=translation_memory_context,
                )
            )
            log_progress(f"translated groups {batch_start + 1}-{min(batch_start + batch_size, len(groups))}/{len(groups)}")
        except Exception as exc:
            warnings.append({
                "reason": "batch_translate_failed_after_adaptive_retry",
                "batch_start": batch_start + 1,
                "batch_size": len(batch_payloads),
                "min_batch_size": min_batch_size,
                "error": str(exc)[:500],
            })

    for group_index, group in enumerate(groups, 1):
        # Log mỗi group + ghi progress JSON để dashboard thấy heartbeat đều.
        log_progress(f"probing/rewrite timing group {group_index}/{len(groups)}")
        write_progress("probing_rewrite", group_index=group_index, total_groups=len(groups), last_action="probe")
        source_text = " ".join(item["source_text"] for item in group).strip()
        start_ms = group[0]["start_ms"]
        end_ms = group[-1]["end_ms"]
        next_start_ms = None
        last_original_index = entries.index(group[-1])
        if last_original_index + 1 < len(entries):
            next_start_ms = entries[last_original_index + 1]["start_ms"]
        slot_ms = max(1, end_ms - start_ms)
        effective_slot_ms = slot_ms
        allowed_overhang_ms = int(CONFIG["allow_audio_overhang"] * 1000)
        if next_start_ms is None:
            effective_slot_ms += allowed_overhang_ms
        else:
            safe_until_next_ms = max(1, next_start_ms - start_ms - 80)
            effective_slot_ms = min(slot_ms + allowed_overhang_ms, safe_until_next_ms)
        report["max_end_overhang"] = max(report["max_end_overhang"], max(0, effective_slot_ms - slot_ms) / 1000)
        if len(group) > 1:
            report["merged_groups"] += 1
        subtitle_per_cue, dub_text = translations.get(group_index, ([], ""))
        translate_failed = False
        if not subtitle_per_cue or not dub_text:
            try:
                subtitle_per_cue, dub_text = translate_group(
                    group,
                    args.api_base,
                    args.api_key,
                    args.model,
                    args.api_provider,
                    translation_memory_context=translation_memory_context,
                )
            except Exception as exc:
                # KHÔNG dùng source_text tiếng Trung làm bản dịch giả. Đánh dấu failed,
                # skip segment (dub rỗng, subtitle rỗng) để run.sh quality gate bắt được.
                translate_failed = True
                subtitle_per_cue = []
                dub_text = ""
                err = str(exc)[:500]
                reason = "rate_limited" if ("429" in err or "Too Many Requests" in err) else "translate_failed"
                warnings.append({"segment_id": group[0]["id"], "reason": reason, "error": err, "source_text": source_text})
                report.setdefault("translate_failed_groups", []).append({
                    "group_index": group_index, "segment_id": group[0]["id"],
                    "reason": reason, "error": err, "source_text": source_text[:200],
                })
        # subtitle_text gộp (cho meaning_check/rewrite) = ghép các bản per-cue.
        subtitle_text = " ".join(part["subtitle_text"] for part in subtitle_per_cue if part.get("subtitle_text")).strip()

        mode = "dub"
        speed_used = 1.0
        rewrite_attempts = 0
        rejected = []
        # Nếu dịch fail, skip probe/rewrite; segment này sẽ rỗng (run.sh quality gate bắt).
        if translate_failed:
            tts_ms = 0
            ratio = 999
            mode = "translate_failed"
            report["translate_failed_segments"] = report.get("translate_failed_segments", 0) + len(group)
        else:
            try:
                tts_ms = synthesize_measure(dub_text, args.voice, work_dir, f"g{group_index:04d}_a0")
                ratio = tts_ms / effective_slot_ms
            except Exception as exc:
                tts_ms = 0
                ratio = 999
                rejected.append({"reason": "tts_probe_failed", "error": str(exc)[:300], "dub_text": dub_text})

        # AI33 duration here is deliberately only a cheap character-rate estimate.
        # Do not shorten, speed-fit, or reject its initial dub_text on this estimate:
        # run.sh performs the required AI33 1.0 synthesis and measures the actual WAV
        # before choosing shorten/restore/keep.  Other engines retain legacy behavior.
        ai33_post_probe_adaptation = (args.voice or "").lower().startswith("ai33")

        if not translate_failed and not ai33_post_probe_adaptation and ratio > CONFIG["rewrite_if_ratio_above"]:
            lock = meaning_lock(source_text, dub_text, args.api_base, args.api_key, args.model, args.api_provider)
            current = dub_text
            for attempt in range(1, CONFIG["max_rewrite_attempts"] + 1):
                rewrite_attempts = attempt
                try:
                    candidate = rewrite_dub(source_text, current, effective_slot_ms / 1000, lock, args.api_base, args.api_key, args.model, args.api_provider)
                except Exception as exc:
                    rejected.append({"reason": "rewrite_error", "error": str(exc)[:300], "dub_text": current})
                    break
                if candidate.strip() == "UNSAFE_TO_REWRITE":
                    report["unsafe_rewrite_segments"] += 1
                    rejected.append({"reason": "unsafe_to_rewrite", "dub_text": current})
                    break
                check = meaning_check(source_text, subtitle_text, candidate, args.api_base, args.api_key, args.model, args.api_provider)
                if not check.get("meaning_preserved") or str(check.get("risk_level", "high")).lower() == "high":
                    report["meaning_check_failed_segments"] += 1
                    rejected.append({"reason": "meaning_check_failed", "check": check, "rejected_dub_text": candidate})
                    break
                try:
                    cand_ms = synthesize_measure(candidate, args.voice, work_dir, f"g{group_index:04d}_a{attempt}")
                    cand_ratio = cand_ms / effective_slot_ms
                except Exception as exc:
                    rejected.append({"reason": "tts_probe_failed_after_rewrite", "error": str(exc)[:300], "dub_text": candidate})
                    break
                dub_text = candidate
                tts_ms = cand_ms
                ratio = cand_ratio
                report["rewritten_segments"] += 1
                if ratio <= CONFIG["rewrite_if_ratio_above"]:
                    break
                current = candidate

        group_duration_seconds = max(0.1, (group[-1]["end_ms"] - group[0]["start_ms"]) / 1000)
        if ai33_post_probe_adaptation:
            mode = "dub"
            speed_used = 1.0
            report["normal_dub_segments"] += len(group)
        elif ratio <= 1.0:
            speed_used = 1.0
            report["normal_dub_segments"] += len(group)
        elif ratio <= CONFIG["max_tts_speed"]:
            speed_used = ratio
            report["speed_adjusted_segments"] += len(group)
            if ratio > CONFIG["soft_max_speed"] and group_duration_seconds > CONFIG["hard_max_duration"]:
                warnings.append({
                    "segment_id": group[0]["id"],
                    "reason": "soft_speed_long_burst",
                    "ratio": round(ratio, 3),
                    "duration_seconds": round(group_duration_seconds, 3),
                    "quality_flag": "REVIEW_FAST_BURST",
                })
        else:
            mode = "subtitle_only"
            speed_used = 1.0
            report["subtitle_only_segments"] += len(group)
            warnings.append({
                "segment_id": group[0]["id"],
                "reason": "subtitle_only_ratio_too_high",
                "source_text": source_text,
                "subtitle_text": subtitle_text,
                "rejected_dub_text": dub_text,
                "ratio": round(ratio, 3) if ratio < 900 else "unknown",
                "rejected": rejected,
            })
        report["max_speed_used"] = max(report["max_speed_used"], min(speed_used, CONFIG["max_tts_speed"]))

        dub_text_out = "" if mode in ("subtitle_only", "translate_failed") else dub_text
        output_entries.append({
            "id": group[0]["id"],
            "group_ids": [item["id"] for item in group],
            "start_ms": group[0]["start_ms"],
            "end_ms": group[-1]["end_ms"],
            "source_text": source_text,
            "subtitle_text": subtitle_text,
            "dub_text": dub_text_out,
            "mode": mode,
            "speed_used": speed_used,
            "tts_ratio": ratio if ratio < 900 else None,
            "rewrite_attempts": rewrite_attempts,
            "tts_probe_ms": tts_ms,
            "tts_probe_kind": "estimate_pending_ai33_natural_probe" if ai33_post_probe_adaptation else "optimizer_probe",
            "effective_slot_ms": effective_slot_ms,
            # The final adaptation metadata is completed in run.sh after AI33's real
            # natural-speed probe. Keeping these fields now makes the hand-off explicit.
            "kept_meaning": [],
            "dropped_details": [],
            "restored_details": [],
            "meaning_risk": "not_evaluated",
            "adapt_direction": "pending_natural_probe" if ai33_post_probe_adaptation else "legacy_optimizer",
            "fit_decision": "await_ai33_natural_tts" if ai33_post_probe_adaptation else "optimizer_decision",
            "quality_flag": "TRANSLATE_FAILED" if translate_failed else ("OK" if speed_used <= CONFIG["target_max_speed"] else ("FAST_BURST" if speed_used <= CONFIG["soft_max_speed"] else "REVIEW_FAST_BURST")),
        })
        # subtitle per-cue: một entry cho mỗi cue gốc, bám timestamp gốc.
        # translate_failed -> subtitle_text rỗng -> write_srt skip.
        if translate_failed:
            cue_texts = ["" for _ in group]
        else:
            cue_texts = [part.get("subtitle_text", "") for part in subtitle_per_cue]
            # Đảm bảo đủ số phần bằng group (fallback distribute đã lo, nhưng phòng xa).
            if len(cue_texts) < len(group):
                distributed = distribute_text(subtitle_text, group) if subtitle_text else ["" for _ in group]
                while len(cue_texts) < len(group):
                    cue_texts.append(distributed[len(cue_texts)] if len(distributed) > len(cue_texts) else "")
        for item, cue_text in zip(group, cue_texts):
            subtitle_entries.append({
                "id": item["id"],
                "start_ms": item["start_ms"],
                "end_ms": item["end_ms"],
                "subtitle_text": cue_text,
                "mode": mode,
            })

    write_srt(args.vietnamese_srt, subtitle_entries, "subtitle_text", skip_subtitle_only=False)
    write_srt(args.dub_srt, output_entries, "dub_text", skip_subtitle_only=True)
    # Số cue thực tế được ghi vào vietnamese.srt (bỏ cue rỗng do write_srt skip).
    vi_cue_count = sum(1 for e in subtitle_entries if (e.get("subtitle_text") or "").strip())
    report["original_cue_count"] = len(entries)
    report["subtitle_cue_count"] = vi_cue_count
    # Dub timing quality: dub.srt phải bám per-cue, không có cue quá dài.
    dub_durs = [(e["end_ms"] - e["start_ms"]) / 1000.0 for e in output_entries
                if (e.get("dub_text") or "").strip()]
    dub_cue_count = len(dub_durs)
    dub_max_cue = max(dub_durs) if dub_durs else 0.0
    dub_overlong = sum(1 for d in dub_durs if d > 8.0)
    dub_long = sum(1 for d in dub_durs if d > 6.0)
    report["dub_timing_quality"] = {
        "dub_cue_count": dub_cue_count,
        "vi_cue_count": vi_cue_count,
        "dub_vi_ratio": round(dub_cue_count / max(1, vi_cue_count), 3),
        "dub_max_cue_seconds": round(dub_max_cue, 3),
        "dub_overlong_cues": dub_overlong,        # > 8s
        "dub_long_cues": dub_long,                # > 6s
    }
    report["translate_failed_groups"] = report.get("translate_failed_groups", [])
    report["translate_failed_segments"] = report.get("translate_failed_segments", 0)
    Path(args.segments_json).write_text(json.dumps(output_entries, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(args.report_json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    failed_groups = report.get("translate_failed_groups") or []
    if failed_groups:
        print(f"Optimizer PARTIAL_FAIL: translate_failed_groups={len(failed_groups)} segments={report['translate_failed_segments']} subtitle_only={report['subtitle_only_segments']}", flush=True)
        # Exit 3 = dịch lỗi hàng loạt; run.sh sẽ quality-gate + chuyển sang manual_translate/pending.
        sys.exit(3)
    print(f"Optimizer OK: segments={report['total_segments']} subtitle_only={report['subtitle_only_segments']} max_speed={report['max_speed_used']:.3f}")


if __name__ == "__main__":
    main()
