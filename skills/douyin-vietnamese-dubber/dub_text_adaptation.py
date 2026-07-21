#!/usr/bin/env python3
"""Pure policy and validation for AI-assisted post-probe dubbing adaptation."""
from __future__ import annotations

from typing import Any


def _is_likely_cut(subtitle_text: str, dub_text: str) -> bool:
    subtitle = (subtitle_text or "").strip()
    dub = (dub_text or "").strip()
    if not subtitle or not dub or subtitle == dub:
        return False
    return len(dub) < max(12, int(len(subtitle) * 0.78))


def decide_adaptation(
    *,
    natural_tts_ms: int,
    slot_ms: int,
    tolerance_ms: int,
    subtitle_text: str,
    dub_text: str,
    restore_ratio: float = 0.72,
) -> dict[str, Any]:
    """Choose direction only after measuring natural TTS at speed 1.0."""
    natural = max(0, int(natural_tts_ms or 0))
    slot = max(1, int(slot_ms or 1))
    if natural > slot + max(0, int(tolerance_ms or 0)):
        return {"adapt_direction": "shorten", "fit_decision": "natural_too_long"}
    if natural < slot * max(0.0, float(restore_ratio)) and _is_likely_cut(subtitle_text, dub_text):
        return {"adapt_direction": "restore_safe_detail", "fit_decision": "natural_short_likely_cut"}
    return {"adapt_direction": "keep_natural", "fit_decision": "use_natural"}


def normalize_adaptation_response(
    response: dict[str, Any] | None,
    *,
    direction: str,
    before_text: str,
    natural_tts_ms: int,
    slot_ms: int,
) -> dict[str, Any]:
    """Reject unsafe/malformed model output before it can reach TTS."""
    response = response if isinstance(response, dict) else {}
    candidate = str(response.get("dub_text") or "").strip().strip('"')
    risk = str(response.get("meaning_risk") or "high").strip().lower()
    if risk not in {"low", "medium", "high"}:
        risk = "high"
    accepted = bool(candidate and candidate != before_text and risk != "high")
    final_direction = direction if accepted else "needs_attention"
    return {
        "accepted": accepted,
        "dub_text": candidate if accepted else before_text,
        "kept_meaning": response.get("kept_meaning") if isinstance(response.get("kept_meaning"), list) else [],
        "dropped_details": response.get("dropped_details") if isinstance(response.get("dropped_details"), list) else [],
        "restored_details": response.get("restored_details") if isinstance(response.get("restored_details"), list) else [],
        "meaning_risk": risk,
        "adapt_direction": final_direction,
        "fit_decision": str(response.get("fit_decision") or ("candidate_rejected" if not accepted else "candidate_pending_probe")),
        "natural_tts_ms": max(0, int(natural_tts_ms or 0)),
        "slot_ms": max(1, int(slot_ms or 1)),
    }
