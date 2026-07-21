"""Measured, text-free policy for unresolved TTS overlap into the next cue."""
import math


DEFAULT_MAX_UNRESOLVED_CONTIGUOUS_OVERHANG_MS = 120


def validated_threshold(value, default=DEFAULT_MAX_UNRESOLVED_CONTIGUOUS_OVERHANG_MS):
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return max(0, int(default))


def unresolved_overhang_event(cue_id, actual_end_ms, next_start_ms, source_cue_ids=None):
    """Return a report-safe event only when audio overlaps the next source cue."""
    if next_start_ms is None:
        return None
    duration_ms = max(0, int(math.ceil(actual_end_ms - next_start_ms)))
    if not duration_ms:
        return None
    event = {
        "cue_id": cue_id,
        "reason": "next_cue_overlap",
        "duration_ms": duration_ms,
    }
    if source_cue_ids is not None:
        event["source_cue_ids"] = list(source_cue_ids)
    return event


def summarize_unresolved_overhang(events, threshold_value):
    """Return bounded report fields and the hard VoiceSync decision."""
    threshold_ms = validated_threshold(threshold_value)
    safe_events = []
    for event in events or []:
        try:
            duration_ms = max(0, int(event.get("duration_ms", 0)))
            cue_id = int(event.get("cue_id"))
        except (AttributeError, TypeError, ValueError):
            continue
        if duration_ms:
            safe_event = {
                "cue_id": cue_id,
                "reason": "next_cue_overlap",
                "duration_ms": duration_ms,
            }
            source_cue_ids = event.get("source_cue_ids")
            if isinstance(source_cue_ids, list):
                safe_event["source_cue_ids"] = source_cue_ids
            safe_events.append(safe_event)
    max_ms = max((event["duration_ms"] for event in safe_events), default=0)
    return {
        "count": len(safe_events),
        "max_ms": max_ms,
        "threshold_ms": threshold_ms,
        "reasons": safe_events,
        "failed": max_ms > threshold_ms,
    }
