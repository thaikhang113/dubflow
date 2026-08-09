"""Durable, offline schema-v1 checkpoints for per-cue TTS WAV output."""

import hashlib
import json
import math
import os
import shutil
import struct
import uuid
import wave
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:
    fcntl = None


SCHEMA_VERSION = 1
MIN_AUDIBLE_RMS = 128

@contextmanager
def _manifest_lock(path):
    """Serialize cross-process checkpoint manifest updates on POSIX hosts."""
    lock_path = Path(path).with_name(Path(path).name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+")
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


class WavValidationError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class CueIdentity:
    def __init__(self, index, text, voice, settings):
        self.index = int(index)
        self.text = str(text)
        self.voice = str(voice)
        self.settings = settings


class CheckpointConfig:
    def __init__(self, source_fingerprint, canonical_voice, settings, total_cues,
                 sample_rate, channels, min_duration_ms, max_duration_ms):
        self.source_fingerprint = str(source_fingerprint)
        self.canonical_voice = str(canonical_voice)
        self.settings = settings
        self.total_cues = int(total_cues)
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.min_duration_ms = int(min_duration_ms)
        self.max_duration_ms = int(max_duration_ms)


def _canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _fingerprint(value):
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def fingerprint_text(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def fingerprint_settings(settings):
    return _fingerprint(settings)


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_canonical_wav(path, config):
    """Return canonical metadata or raise a stable, secret-free validation code."""
    try:
        with wave.open(str(path), "rb") as input_wav:
            rate = input_wav.getframerate()
            channels = input_wav.getnchannels()
            width = input_wav.getsampwidth()
            frames = input_wav.getnframes()
            compression = input_wav.getcomptype()
            raw = input_wav.readframes(frames)
    except (OSError, EOFError, wave.Error):
        raise WavValidationError("wav_invalid")
    if compression != "NONE" or width != 2 or frames <= 0:
        raise WavValidationError("wav_invalid")
    if rate != config.sample_rate:
        raise WavValidationError("sample_rate_mismatch")
    if channels != config.channels:
        raise WavValidationError("channels_mismatch")
    duration_ms = frames * 1000.0 / rate
    if not config.min_duration_ms <= duration_ms <= config.max_duration_ms:
        raise WavValidationError("duration_invalid")
    # Canonical PCM is signed 16-bit little endian. Reject provider noise floors
    # that contain non-zero samples but no usable speech.
    samples = struct.iter_unpack("<h", raw)
    rms = math.sqrt(sum(sample * sample for sample, in samples) / max(1, frames * channels))
    if rms < MIN_AUDIBLE_RMS:
        raise WavValidationError("wav_silent")
    return {
        "sample_rate": rate,
        "channels": channels,
        "duration_ms": int(round(duration_ms)),
        "checksum": _sha256(path),
    }


def _blank_manifest():
    return {"schema_version": SCHEMA_VERSION, "cues": {}}


def _clean_stale_temps(path):
    path = Path(path)
    for candidate in path.parent.glob(path.name + ".tmp-*"):
        if candidate.is_file():
            candidate.unlink(missing_ok=True)


def load_checkpoint(path):
    path = Path(path)
    _clean_stale_temps(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _blank_manifest()
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION or not isinstance(data.get("cues"), dict):
        return _blank_manifest()
    return data


def _atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _clean_stale_temps(path)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            directory = os.open(str(path.parent), getattr(os, "O_DIRECTORY", 0))
            try: os.fsync(directory)
            finally: os.close(directory)
        except OSError:
            pass
    finally:
        temporary.unlink(missing_ok=True)


def _manifest_for_config(manifest, config):
    manifest.update({
        "schema_version": SCHEMA_VERSION,
        "source_fingerprint": config.source_fingerprint,
        "canonical_voice": config.canonical_voice,
        "settings_fingerprint": fingerprint_settings(config.settings),
        "total_cues": config.total_cues,
    })
    manifest.setdefault("cues", {})
    return manifest


def _identity_matches_config(identity, config):
    return identity.voice == config.canonical_voice and fingerprint_settings(identity.settings) == fingerprint_settings(config.settings)


def _require_valid_identity(identity, config):
    if identity.index < 0 or identity.index >= config.total_cues or not _identity_matches_config(identity, config):
        raise ValueError("cue identity does not match checkpoint configuration")


def _cue_entry(identity, config, metadata, wav_path, attempts):
    return {
        "status": "completed", "validated": True, "index": identity.index,
        "text_fingerprint": fingerprint_text(identity.text), "voice": identity.voice,
        "settings_fingerprint": fingerprint_settings(identity.settings),
        "sample_rate": metadata["sample_rate"], "channels": metadata["channels"],
        "duration_ms": metadata["duration_ms"], "wav_checksum": metadata["checksum"],
        "wav_path": str(Path(wav_path)), "attempts": int(attempts),
    }


def complete_cue(manifest_path, config, identity, wav_path, attempts):
    _require_valid_identity(identity, config)
    metadata = validate_canonical_wav(wav_path, config)
    with _manifest_lock(manifest_path):
        manifest = _manifest_for_config(load_checkpoint(manifest_path), config)
        entry = _cue_entry(identity, config, metadata, wav_path, attempts)
        manifest["cues"][str(identity.index)] = entry
        _atomic_write(manifest_path, manifest)
    return entry


def reusable_cue(manifest_path, config, identity):
    if identity.index < 0 or identity.index >= config.total_cues or not _identity_matches_config(identity, config):
        return False
    manifest = load_checkpoint(manifest_path)
    if (manifest.get("source_fingerprint"), manifest.get("canonical_voice"), manifest.get("settings_fingerprint"), manifest.get("total_cues")) != (
        config.source_fingerprint, config.canonical_voice, fingerprint_settings(config.settings), config.total_cues):
        return False
    entry = manifest.get("cues", {}).get(str(identity.index))
    if not isinstance(entry, dict) or entry.get("status") != "completed" or entry.get("validated") is not True:
        return False
    expected = (identity.index, fingerprint_text(identity.text), identity.voice, fingerprint_settings(identity.settings), config.sample_rate, config.channels)
    actual = (entry.get("index"), entry.get("text_fingerprint"), entry.get("voice"), entry.get("settings_fingerprint"), entry.get("sample_rate"), entry.get("channels"))
    if actual != expected:
        return False
    try:
        metadata = validate_canonical_wav(entry.get("wav_path", ""), config)
    except (OSError, TypeError, WavValidationError):
        return False
    return metadata["checksum"] == entry.get("wav_checksum") and metadata["duration_ms"] == entry.get("duration_ms")


def record_failure(manifest_path, config, identity, stage, error_code, attempts, _detail=""):
    _require_valid_identity(identity, config)
    with _manifest_lock(manifest_path):
        manifest = _manifest_for_config(load_checkpoint(manifest_path), config)
        entry = {"status": "failed", "validated": False, "index": identity.index,
                 "text_fingerprint": fingerprint_text(identity.text), "voice": identity.voice,
                 "settings_fingerprint": fingerprint_settings(identity.settings), "stage": str(stage),
                 "error_code": str(error_code), "attempts": int(attempts)}
        manifest["cues"][str(identity.index)] = entry
        _atomic_write(manifest_path, manifest)
    return entry


def materialize_cue(manifest_path, config, identity, output_path):
    """Atomically copy one fully revalidated checkpoint cue into a run segment."""
    if not reusable_cue(manifest_path, config, identity):
        raise WavValidationError("cue_not_reusable")
    source = Path(load_checkpoint(manifest_path)["cues"][str(identity.index)]["wav_path"])
    target = Path(output_path)
    if source.resolve() == target.resolve():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp-" + uuid.uuid4().hex)
    try:
        shutil.copyfile(source, temporary)
        source_metadata = validate_canonical_wav(source, config)
        copied_metadata = validate_canonical_wav(temporary, config)
        if copied_metadata["checksum"] != source_metadata["checksum"]:
            raise WavValidationError("checksum_mismatch")
        with temporary.open("rb+") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def materialize_completed_wav(manifest_path, cue_index, output_path):
    """Shared atomic materialization for callers that already performed reuse validation."""
    manifest = load_checkpoint(manifest_path)
    entry = manifest.get("cues", {}).get(str(cue_index))
    if not isinstance(entry, dict):
        raise WavValidationError("cue_not_reusable")
    config = CheckpointConfig("", "", {}, 1, entry.get("sample_rate", 0), entry.get("channels", 0), 1, 1800000)
    source = Path(entry.get("wav_path", ""))
    metadata = validate_canonical_wav(source, config)
    if metadata["checksum"] != entry.get("wav_checksum"):
        raise WavValidationError("checksum_mismatch")
    target = Path(output_path)
    if source.resolve() == target.resolve():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp-" + uuid.uuid4().hex)
    try:
        shutil.copyfile(source, temporary)
        if validate_canonical_wav(temporary, config)["checksum"] != metadata["checksum"]:
            raise WavValidationError("checksum_mismatch")
        with temporary.open("rb+") as handle: os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def import_legacy_wav(manifest_path, config, identity, legacy_wav_path, canonical_wav_path, attempts):
    """Validate caller-identified legacy audio, then atomically promote it to canonical storage."""
    _require_valid_identity(identity, config)
    metadata = validate_canonical_wav(legacy_wav_path, config)
    target = Path(canonical_wav_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp-" + uuid.uuid4().hex)
    try:
        shutil.copyfile(legacy_wav_path, temporary)
        with temporary.open("rb+") as handle:
            os.fsync(handle.fileno())
        promoted = validate_canonical_wav(temporary, config)
        if promoted["checksum"] != metadata["checksum"]:
            raise WavValidationError("checksum_mismatch")
        os.replace(temporary, target)
        try:
            directory = os.open(str(target.parent), getattr(os, "O_DIRECTORY", 0))
            try: os.fsync(directory)
            finally: os.close(directory)
        except OSError:
            pass
    finally:
        temporary.unlink(missing_ok=True)
    return complete_cue(manifest_path, config, identity, target, attempts)
