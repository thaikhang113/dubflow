"""Pure, provider-safe timing policy for AI33 TTS.

The provider accepts numeric speed.  UI-only semantic tags are intentionally not
injected until their API contract is documented.
"""


def canonical_speed_contract(required_speed, *, native_max_speed, total_max_speed,
                             residual_atempo_max=1.03, native_supported=True,
                             measured_overlong=False):
    """Return one native request and a bounded, post-measurement residual cap.

    Callers request ``native_speed`` once, then may apply no more than
    ``post_atempo_max`` after measuring the resulting WAV.  The total factor
    cannot exceed the quality budget, preventing routine multiplicative speed.
    """
    try:
        requested = max(1.0, float(required_speed))
    except (TypeError, ValueError):
        requested = 1.0
    native_cap = max(1.0, float(native_max_speed))
    # Native and total caps are independent: the provider request is bounded by
    # native_cap, while ffmpeg may only consume the residual of total_cap.
    total_cap = max(1.0, float(total_max_speed))
    native_speed = min(requested, native_cap, total_cap) if native_supported else 1.0
    native_mode = "numeric" if native_supported and native_speed > 1.0005 else (
        "not_requested" if native_supported else "unavailable"
    )
    routine_residual = max(1.0, float(residual_atempo_max))
    residual_limit = total_cap / native_speed
    if not measured_overlong:
        residual_limit = min(routine_residual, residual_limit)
    post_atempo_max = 1.0 if requested <= native_speed + 0.0005 else min(residual_limit, requested / native_speed)
    return {
        "native_speed_mode": native_mode,
        "native_speed": round(native_speed, 4),
        "post_atempo_max": round(post_atempo_max, 4),
        "total_speed_factor": round(native_speed * post_atempo_max, 4),
    }


def measured_post_atempo_fit(*, actual_duration_ms, allowed_duration_ms,
                             native_speed, total_max_speed,
                             routine_post_atempo_max, adaptation_needs_attention,
                             adaptation_fit_eligible=False):
    """Choose the minimum measured post-tempo factor without changing text.

    Routine fit remains gentle.  Only a cue still overlong after a semantic
    adaptation attempt/rejection or an accepted pending-fit candidate may use
    the remaining total-speed budget.  Eligibility does not alter the semantic
    attention outcome reported to callers.
    """
    actual_ms = max(0.0, float(actual_duration_ms))
    allowed_ms = max(1.0, float(allowed_duration_ms))
    native = max(1.0, float(native_speed))
    total_cap = max(1.0, float(total_max_speed))
    routine_cap = max(1.0, float(routine_post_atempo_max))
    needed = max(1.0, actual_ms / allowed_ms)
    rescue = actual_ms > allowed_ms and (
        bool(adaptation_needs_attention) or bool(adaptation_fit_eligible)
    )
    cap = total_cap / native if rescue else min(routine_cap, total_cap / native)
    factor = min(needed, cap)
    return {
        "post_atempo_factor": round(factor, 4),
        "total_speed_factor": round(native * factor, 4),
        "decision": "measured_overlong_rescue" if rescue else "routine_fit",
        "adaptation_needs_attention": bool(adaptation_needs_attention),
    }
