"""Resource-aware worker planning for pipeline stages."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkerDecision:
    requested: int
    effective: int
    reason: str

    def to_dict(self) -> dict[str, int | str]:
        return {
            "requested": self.requested,
            "effective": self.effective,
            "reason": self.reason,
        }


def _decision(requested: int, effective: int, reason: str) -> dict:
    return WorkerDecision(
        requested=max(1, int(requested)),
        effective=max(1, int(effective)),
        reason=reason,
    ).to_dict()


def build_worker_plan(
    *,
    mode: str = "auto",
    cpu_count: int | None,
    available_ram_gb: float | None,
    gpu_available: bool,
    configured: dict[str, int] | None = None,
) -> dict[str, dict]:
    """Build effective worker counts with conservative resource caps."""
    configured = configured or {}
    cpu = max(1, int(cpu_count or 1))
    requested_parallel = max(1, int(configured.get("parallel", max(2, cpu // 2))))
    requested_tts = max(1, int(configured.get("tts", 3)))
    requested_asr = max(1, int(configured.get("asr", 4)))
    low = available_ram_gb is not None and available_ram_gb < 3.0
    constrained = available_ram_gb is not None and available_ram_gb < 5.0
    if available_ram_gb is None:
        ram_cap = 3
    elif low:
        ram_cap = 1
    elif constrained:
        ram_cap = 2
    else:
        ram_cap = 6

    if mode == "auto":
        requested_tts = ram_cap
        requested_parallel = min(8, max(1, cpu // 2))
        requested_asr = min(4, max(1, cpu // 4))

    tts = min(requested_tts, ram_cap, max(1, cpu // 2))
    parallel = min(requested_parallel, 1 if low else 2 if constrained else 8,
                   max(1, cpu // 2))
    asr = min(requested_asr, 1 if low else 2 if constrained else 4,
              max(1, cpu // 4))
    reason = "auto resource cap" if mode == "auto" else "manual request capped"
    if available_ram_gb is None:
        reason = "safe default; RAM unavailable"

    return {
        "tts": _decision(requested_tts, tts, reason),
        "parallel": _decision(requested_parallel, parallel, reason),
        "asr": _decision(requested_asr, asr, reason),
        "ocr": _decision(1, 1, "single model worker"),
        "demucs": _decision(1, 1, "single model worker"),
        "translate": _decision(requested_parallel, parallel, reason),
        "merge": _decision(requested_parallel, parallel, reason),
        "gpu": {"available": bool(gpu_available)},
    }
