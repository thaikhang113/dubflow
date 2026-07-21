#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import voice_registry as vr


def assert_eq(actual, expected, message):
    if actual != expected:
        raise AssertionError(f"{message}: got {actual!r}, expected {expected!r}")


def assert_raises_contains(func, text, message):
    try:
        func()
    except Exception as exc:
        if text not in str(exc):
            raise AssertionError(f"{message}: wrong error {exc!r}") from exc
        return
    raise AssertionError(f"{message}: expected error containing {text!r}")


def test_default_and_aliases():
    reg = vr.load_registry(Path(__file__).with_name("voice_registry.default.json"))
    mai = "ai33:vbee_hn_female_maiphuong_vdts_48k-fhg"
    phanh = "ai33:elevenlabs_UuMSQK8FdLwaY2M8ZAnh"
    assert_eq(vr.default_voice(reg), mai, "Mai Phuong must be default")
    for alias in ("", "ai33", "maiphuong", "vbee", "vbee_hn_female_maiphuong_vdts_48k-fhg"):
        assert_eq(vr.normalize_ai33_voice(alias, reg), mai, f"alias {alias}")
    assert_eq(vr.normalize_ai33_voice("phanh", reg), phanh, "phanh alias")
    assert_eq(vr.ai33_metadata("maiphuong", reg)["min_slow_ratio"], 0.85, "timing floor")


def test_voice_timing_overrides_are_preserved():
    data = {
        "default_voice": "ai33:review_voice",
        "voices": [
            {
                "provider": "ai33",
                "voice_id": "review_voice",
                "label": "Review",
                "aliases": ["review"],
                "enabled": True,
                "timing_profile": "ai33_review_film_current",
                "min_slow_ratio": 0.85,
                "timing_overrides": {
                    "ai33_max_speed": 1.12,
                    "post_atempo_max": 1.05,
                    "total_audio_speed_max": 1.35,
                },
                "dub_text_overrides": {
                    "restore_if_slot_ratio_below": 0.82,
                },
            }
        ],
    }
    metadata = vr.ai33_metadata("review", vr.validate_registry(data))
    assert_eq(metadata["timing_profile"], "ai33_review_film_current", "profile name")
    assert_eq(
        metadata["timing_overrides"],
        {"ai33_max_speed": 1.12, "post_atempo_max": 1.05, "total_audio_speed_max": 1.35},
        "timing overrides",
    )
    assert_eq(
        metadata["dub_text_overrides"],
        {"restore_if_slot_ratio_below": 0.82},
        "dub text overrides",
    )


def test_pipeline_reads_voice_timing_overrides_static():
    run_sh = Path(__file__).with_name("run.sh").read_text(encoding="utf-8")
    required = [
        "def apply_ai33_timing_overrides",
        "timing_overrides_applied",
        "apply_ai33_timing_overrides(ai33_voice_meta)",
        "def apply_ai33_dub_text_overrides",
        "dub_text_overrides_applied",
        "apply_ai33_dub_text_overrides(ai33_voice_meta)",
    ]
    missing = [needle for needle in required if needle not in run_sh]
    if missing:
        raise AssertionError(f"pipeline missing voice timing override support: {missing}")


def test_duplicate_alias_rejected():
    data = {
        "default_voice": "ai33:a_voice",
        "voices": [
            {"provider": "ai33", "voice_id": "a_voice", "label": "A", "aliases": ["same"], "enabled": True},
            {"provider": "ai33", "voice_id": "b_voice", "label": "B", "aliases": ["same"], "enabled": True},
        ],
    }
    assert_raises_contains(lambda: vr.validate_registry(data), "alias trùng", "duplicate alias")


def test_canonical_voice_id_input_is_cleaned():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "voice_registry.json"
        vr.seed_runtime(path)
        vr.add_ai33_voice(
            {
                "voice_id": "ai33:vbee_new_canonical_input",
                "label": "Canonical Input",
                "aliases": "canonical-input",
                "set_default": True,
            },
            path,
        )
        reg = vr.load_registry(path)
        assert_eq(vr.default_voice(reg), "ai33:vbee_new_canonical_input", "canonical voice_id input")
        assert_eq(vr.ai33_metadata("canonical-input", reg)["voice_id"], "vbee_new_canonical_input", "stored raw voice_id")


def test_voice_link_input_is_extracted_offline():
    assert_eq(
        vr.extract_ai33_voice_id("https://ai33.pro/voices/detail?voice_id=vbee_link_voice_48k-fhg"),
        "vbee_link_voice_48k-fhg",
        "query voice_id",
    )
    assert_eq(
        vr.extract_ai33_voice_id("https://ai33.pro/library/voices/vbee_path_voice_48k-fhg"),
        "vbee_path_voice_48k-fhg",
        "path voice id",
    )
    assert_eq(
        vr.extract_ai33_voice_id('{"voiceId":"elevenlabs_LinkVoice123"}'),
        "elevenlabs_LinkVoice123",
        "json voiceId",
    )


def test_alias_cannot_shadow_other_voice_id():
    data = {
        "default_voice": "ai33:a_voice",
        "voices": [
            {"provider": "ai33", "voice_id": "a_voice", "label": "A", "aliases": ["b_voice"], "enabled": True},
            {"provider": "ai33", "voice_id": "b_voice", "label": "B", "aliases": [], "enabled": True},
        ],
    }
    assert_raises_contains(lambda: vr.validate_registry(data), "alias trùng", "alias cannot shadow voice_id")


def test_corrupt_registry_reports_invalid():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "voice_registry.json"
        path.write_text("{not-json", encoding="utf-8")
        assert_raises_contains(lambda: vr.load_registry(path), "VoiceRegistryInvalid", "corrupt registry")


def test_empty_runtime_registry_env_uses_default_path():
    env = dict(os.environ)
    env["OPENCLAW_VOICE_REGISTRY_JSON"] = ""
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import voice_registry as vr; print(vr.RUNTIME_REGISTRY)",
        ],
        cwd=str(Path(__file__).resolve().parent),
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise AssertionError(f"empty env import failed: {proc.stderr}")
    assert_eq(
        proc.stdout.strip(),
        "/home/haonguyen/.openclaw/config/voice_registry.json",
        "empty OPENCLAW_VOICE_REGISTRY_JSON must not resolve to current directory",
    )


def test_add_disable_restore_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "voice_registry.json"
        reg = vr.seed_runtime(path)
        assert_eq(reg["default_voice"], "ai33:vbee_hn_female_maiphuong_vdts_48k-fhg", "seed default")
        vr.add_ai33_voice(
            {
                "voice_id": "vbee_new_test_voice",
                "label": "New Test",
                "aliases": "newtest, testvoice",
                "set_default": True,
            },
            path,
        )
        assert_eq(vr.normalize_ai33_voice("newtest", vr.load_registry(path)), "ai33:vbee_new_test_voice", "new alias")
        assert_raises_contains(lambda: vr.disable_voice("newtest", path), "VoiceDefaultDisableBlocked", "cannot disable default")
        vr.set_default_voice("maiphuong", path)
        vr.disable_voice("newtest", path)
        reg = json.loads(path.read_text(encoding="utf-8"))
        assert any(not v.get("enabled", True) for v in reg["voices"] if v["voice_id"] == "vbee_new_test_voice")
        restored = vr.restore_latest_backup(path)
        assert restored["default_voice"].startswith("ai33:"), "restored registry stays valid"


if __name__ == "__main__":
    test_default_and_aliases()
    test_voice_timing_overrides_are_preserved()
    test_pipeline_reads_voice_timing_overrides_static()
    test_duplicate_alias_rejected()
    test_canonical_voice_id_input_is_cleaned()
    test_voice_link_input_is_extracted_offline()
    test_alias_cannot_shadow_other_voice_id()
    test_corrupt_registry_reports_invalid()
    test_empty_runtime_registry_env_uses_default_path()
    test_add_disable_restore_roundtrip()
    print("ALL PASS")
