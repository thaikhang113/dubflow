"""Small offline orchestration seam for exact AI33 cue resume.

It deliberately owns no upstream ASR/OCR/translation behavior: callers provide
already-final TTS cues and a provider callable.
"""
import hashlib
import importlib.util
import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("tts_checkpoint", _HERE / "tts_checkpoint.py")
checkpoint = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(checkpoint)


def make_config(cues, canonical_voice, settings, sample_rate, channels):
    # Global source identity covers the final subtitle timing topology. Per-cue
    # dub text is independently fingerprinted by CueIdentity so one edit only
    # invalidates that cue instead of discarding otherwise valid audio.
    source = [{"start_ms": int(start), "end_ms": int(end)} for _text, start, end in cues]
    source_fingerprint = hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return checkpoint.CheckpointConfig(source_fingerprint, canonical_voice, settings, len(cues), sample_rate, channels, 1, 1800000)


def run_cues(root, cues, config, provider, upstream_hook=None, require_complete=True):
    """Materialize every cue; provider is called only for invalid/missing cues."""
    del upstream_hook  # Regression guard: resume cannot invoke upstream work.
    root = Path(root); manifest = root / "tts_checkpoint.json"; canonical = root / "tts_checkpoint_wavs"; segments = root / "tts_segments"
    completed = reused = 0; master_inputs = []
    for ordinal, (text, _start, _end) in enumerate(cues, 1):
        identity = checkpoint.CueIdentity(ordinal - 1, text, config.canonical_voice, config.settings)
        output = segments / f"{ordinal:04d}_speech.wav"
        if checkpoint.reusable_cue(manifest, config, identity):
            checkpoint.materialize_cue(manifest, config, identity, output); reused += 1
        else:
            generated = canonical / f"{ordinal:04d}_speech.wav"
            try:
                attempts = int(provider(ordinal, text, generated) or 1)
                checkpoint.complete_cue(manifest, config, identity, generated, attempts)
                checkpoint.materialize_cue(manifest, config, identity, output)
            except Exception as exc:
                checkpoint.record_failure(manifest, config, identity, "provider", getattr(exc, "code", "TTSProviderFailed"), 0)
                raise
        completed += 1; master_inputs.append(output)
    if require_complete and completed != config.total_cues:
        raise RuntimeError(f"cue coverage incomplete {completed}/{config.total_cues}")
    return {"completed": completed, "reused": reused, "master_inputs": master_inputs, "checkpoint_path": manifest.name}
