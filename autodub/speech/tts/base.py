"""Shared TTS types: result dataclass and synthesizer protocol."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Protocol


@dataclass
class TTSResult:
    path: str
    actual_duration: float
    speed_adjusted: bool
    rate_applied: str

    def to_dict(self) -> dict:
        return asdict(self)


def write_silence(output_path: str, duration_s: float = 0.05,
                  sample_rate: int = 24000) -> TTSResult:
    """Write a short silent WAV — the safe render for an empty text line.

    Hand-edited transcripts can contain blank/punctuation-only lines; feeding
    "" to a TTS model crashes or hangs the worker, and failing the whole run
    over one blank line is worse than a near-silent clip in its place.
    """
    import struct
    import wave

    n_frames = max(1, int(duration_s * sample_rate))
    with wave.open(output_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(struct.pack(f"<{n_frames}h", *([0] * n_frames)))
    return TTSResult(
        path=output_path,
        actual_duration=round(n_frames / sample_rate, 3),
        speed_adjusted=False,
        rate_applied="silence",
    )


class Synthesizer(Protocol):
    """A per-segment TTS engine. One instance per pipeline run (voice is fixed)."""

    def synthesize(
        self,
        text: str,
        output_path: str,
        target_duration: float | None = None,
    ) -> TTSResult:
        ...
