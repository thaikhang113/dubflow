#!/usr/bin/env python3
"""Offline contract tests for schema-v1 per-cue TTS checkpointing."""

import hashlib
import importlib.util
import json
import struct
import tempfile
import unittest
import wave
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("tts_checkpoint", SKILL_DIR / "tts_checkpoint.py")
checkpoint = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checkpoint)


def write_wav(path, rate=24000, channels=1, frames=2400, sample=700):
    values = [sample] * (frames * channels)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(struct.pack("<" + "h" * len(values), *values))


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manifest = self.root / "tts_checkpoint.json"
        self.wav = self.root / "input.wav"
        write_wav(self.wav)
        self.identity = checkpoint.CueIdentity(0, "Xin chao", "vi_female", {"speed": 1.0})
        self.config = checkpoint.CheckpointConfig("source-1", "vi_female", {"speed": 1.0}, 1, 24000, 1, 50, 10000)

    def tearDown(self): self.temp.cleanup()

    def complete(self):
        return checkpoint.complete_cue(self.manifest, self.config, self.identity, self.wav, attempts=2)

    def test_atomic_round_trip_and_canonical_manifest(self):
        cue = self.complete()
        data = json.loads(self.manifest.read_text())
        self.assertEqual(1, data["schema_version"])
        self.assertEqual("source-1", data["source_fingerprint"])
        self.assertEqual("vi_female", data["canonical_voice"])
        self.assertEqual(1, data["total_cues"])
        self.assertEqual("completed", data["cues"]["0"]["status"])
        self.assertTrue(cue["validated"])
        self.assertTrue(checkpoint.reusable_cue(self.manifest, self.config, self.identity))

    def test_interrupted_temp_is_cleaned_and_main_is_preserved(self):
        self.complete()
        original = self.manifest.read_bytes()
        stale = self.manifest.with_name(self.manifest.name + ".tmp-stale")
        stale.write_text("partial")
        loaded = checkpoint.load_checkpoint(self.manifest)
        self.assertEqual("source-1", loaded["source_fingerprint"])
        self.assertEqual(original, self.manifest.read_bytes())
        self.assertFalse(stale.exists())

    def test_missing_wav_is_not_reusable(self):
        cue = self.complete(); Path(cue["wav_path"]).unlink()
        self.assertFalse(checkpoint.reusable_cue(self.manifest, self.config, self.identity))

    def test_checksum_mismatch_is_not_reusable(self):
        cue = self.complete()
        with Path(cue["wav_path"]).open("ab") as handle: handle.write(b"changed")
        self.assertFalse(checkpoint.reusable_cue(self.manifest, self.config, self.identity))

    def test_corrupt_wav_is_rejected(self):
        corrupt = self.root / "corrupt.wav"; corrupt.write_bytes(b"not a wav")
        with self.assertRaises(checkpoint.WavValidationError) as raised:
            checkpoint.complete_cue(self.manifest, self.config, self.identity, corrupt, 1)
        self.assertEqual("wav_invalid", raised.exception.code)

    def test_silent_wav_is_rejected(self):
        silent = self.root / "silent.wav"; write_wav(silent, sample=0)
        with self.assertRaisesRegex(checkpoint.WavValidationError, "wav_silent"):
            checkpoint.complete_cue(self.manifest, self.config, self.identity, silent, 1)

    def test_rate_channel_and_duration_are_validated(self):
        wrong_rate = self.root / "rate.wav"; write_wav(wrong_rate, rate=16000)
        wrong_channels = self.root / "channels.wav"; write_wav(wrong_channels, channels=2)
        too_long = self.root / "long.wav"; write_wav(too_long, frames=300000)
        for candidate, code in ((wrong_rate, "sample_rate_mismatch"), (wrong_channels, "channels_mismatch"), (too_long, "duration_invalid")):
            with self.assertRaises(checkpoint.WavValidationError) as raised:
                checkpoint.complete_cue(self.manifest, self.config, self.identity, candidate, 1)
            self.assertEqual(code, raised.exception.code)

    def test_text_voice_speed_and_settings_changes_invalidate(self):
        self.complete()
        variants = (
            checkpoint.CueIdentity(0, "Da thay", "vi_female", {"speed": 1.0}),
            checkpoint.CueIdentity(0, "Xin chao", "other_voice", {"speed": 1.0}),
            checkpoint.CueIdentity(0, "Xin chao", "vi_female", {"speed": 1.1}),
        )
        for identity in variants: self.assertFalse(checkpoint.reusable_cue(self.manifest, self.config, identity))
        changed = checkpoint.CheckpointConfig("source-1", "vi_female", {"speed": 1.1}, 1, 24000, 1, 50, 10000)
        self.assertFalse(checkpoint.reusable_cue(self.manifest, changed, self.identity))

    def test_selective_text_invalidation_keeps_other_cue(self):
        other = checkpoint.CueIdentity(1, "Cue two", "vi_female", {"speed": 1.0})
        config = checkpoint.CheckpointConfig("source-1", "vi_female", {"speed": 1.0}, 2, 24000, 1, 50, 10000)
        checkpoint.complete_cue(self.manifest, config, self.identity, self.wav, 1)
        checkpoint.complete_cue(self.manifest, config, other, self.wav, 1)
        self.assertFalse(checkpoint.reusable_cue(self.manifest, config, checkpoint.CueIdentity(0, "Edited", "vi_female", {"speed": 1.0})))
        self.assertTrue(checkpoint.reusable_cue(self.manifest, config, other))

    def test_source_voice_and_global_settings_mismatch_invalidate_reuse(self):
        self.complete()
        for config in (
            checkpoint.CheckpointConfig("source-2", "vi_female", {"speed": 1.0}, 1, 24000, 1, 50, 10000),
            checkpoint.CheckpointConfig("source-1", "new_voice", {"speed": 1.0}, 1, 24000, 1, 50, 10000),
            checkpoint.CheckpointConfig("source-1", "vi_female", {"speed": 0.9}, 1, 24000, 1, 50, 10000),
        ): self.assertFalse(checkpoint.reusable_cue(self.manifest, config, self.identity))

    def test_failed_entry_redacts_url_and_tracks_stage_error_and_attempts(self):
        entry = checkpoint.record_failure(self.manifest, self.config, self.identity, "download", "network_failed", 3, "GET https://provider.example/signed?token=no")
        self.assertEqual(("failed", "download", "network_failed", 3), (entry["status"], entry["stage"], entry["error_code"], entry["attempts"]))
        self.assertNotIn("provider.example", json.dumps(entry))
        self.assertFalse(checkpoint.reusable_cue(self.manifest, self.config, self.identity))

    def test_legacy_import_requires_identity_and_full_validation_then_promotes_atomically(self):
        target = self.root / "canonical" / "cue-000.wav"
        with self.assertRaises(TypeError): checkpoint.import_legacy_wav(self.manifest, self.config, self.wav)
        entry = checkpoint.import_legacy_wav(self.manifest, self.config, self.identity, self.wav, target, 4)
        self.assertEqual(str(target), entry["wav_path"])
        self.assertTrue(target.exists())
        self.assertTrue(checkpoint.reusable_cue(self.manifest, self.config, self.identity))

    def test_materialize_validated_cue_is_atomic_and_keeps_checksum(self):
        self.complete()
        output = self.root / "segments" / "0000_speech.wav"
        checkpoint.materialize_cue(self.manifest, self.config, self.identity, output)
        self.assertTrue(output.exists())
        self.assertEqual(checkpoint._sha256(self.wav), checkpoint._sha256(output))

    def test_fingerprints_are_deterministic(self):
        self.assertEqual(checkpoint.fingerprint_settings({"b": 2, "a": 1}), checkpoint.fingerprint_settings({"a": 1, "b": 2}))
        self.assertEqual(checkpoint.fingerprint_text("Xin chao"), hashlib.sha256("Xin chao".encode()).hexdigest())


if __name__ == "__main__": unittest.main()
