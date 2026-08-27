import json

from autodub_gui import bootstrap


def test_bootstrap_state_round_trip(monkeypatch, tmp_path):
    monkeypatch.setattr(bootstrap, "data_root", lambda: str(tmp_path))
    assert bootstrap.is_complete() is False

    bootstrap.mark_completed("ffmpeg")
    state = bootstrap.load_state()
    assert state["completed"]["ffmpeg"] is True

    bootstrap.mark_failed("whisper", "offline")
    state = bootstrap.load_state()
    assert state["failed"]["whisper"] == "offline"

    bootstrap.mark_completed("whisper")
    state = bootstrap.load_state()
    assert "whisper" not in state["failed"]


def test_bootstrap_state_recovers_from_corrupt_file(monkeypatch, tmp_path):
    monkeypatch.setattr(bootstrap, "data_root", lambda: str(tmp_path))
    (tmp_path / bootstrap.STATE_NAME).write_text("{", encoding="utf-8")
    assert bootstrap.load_state()["version"] == bootstrap.STATE_VERSION

def test_bootstrap_requires_hardware_plan_for_legacy_state(monkeypatch, tmp_path):
    monkeypatch.setattr(bootstrap, "data_root", lambda: str(tmp_path))
    bootstrap.save_state({
        "version": bootstrap.STATE_VERSION,
        "completed": {step.key: True for step in bootstrap.steps()},
        "failed": {},
    })

    assert bootstrap.is_complete() is False


def test_bootstrap_steps_include_all_engines(monkeypatch, tmp_path):
    monkeypatch.setattr(bootstrap, "data_root", lambda: str(tmp_path))
    keys = [step.key for step in bootstrap.steps()]
    expected = ["hardware", "python", "vieneu", "whisper", "paraformer",
                "ocr", "douyin", "demucs", "voices"]
    if not bootstrap.sys.platform.startswith("linux"):
        expected.insert(2, "ffmpeg")
    assert keys == expected
    assert bootstrap.steps()[0].kind == "hardware"
    assert bootstrap.steps()[1].kind == "python"
    if not bootstrap.sys.platform.startswith("linux"):
        assert bootstrap.steps()[2].kind == "ffmpeg"
    assert bootstrap.steps()[-2].script == "scripts/setup_demucs.py"

def test_bootstrap_steps_follow_backend_plan(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_OCR_ENABLED", "true")
    plan = bootstrap.BackendPlan(
        "deepseek-rocm", "video-subtitle-remover", ("test",))
    keys = [step.key for step in bootstrap.steps(plan)]
    assert "deepseek_ocr" in keys
    assert "ocr" not in keys
    assert keys[-1] == "vsr"

def test_bootstrap_steps_skip_deepseek_when_disabled(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_OCR_ENABLED", "false")
    plan = bootstrap.BackendPlan(
        "deepseek-rocm", "fallback", ("legacy plan",))

    keys = [step.key for step in bootstrap.steps(plan)]

    assert "deepseek_ocr" not in keys
    assert "ocr" in keys

def test_ensure_hardware_plan_replaces_disabled_deepseek_plan(
    monkeypatch, tmp_path
):
    from autodub.hardware import HardwareProfile

    monkeypatch.setenv("DEEPSEEK_OCR_ENABLED", "false")
    monkeypatch.setattr(bootstrap, "data_root", lambda: str(tmp_path))
    profile = HardwareProfile(
        platform="linux",
        machine="x86_64",
        python="3.12",
        ram_gb=16,
        disk_free_gb=20,
        gpu_vendor="amd",
        gpu_name="AMD Radeon RX 6600",
        amd=True,
        rocm=True,
        vulkan=True,
    )
    monkeypatch.setattr(bootstrap, "detect_hardware", lambda disk_path: profile)
    (tmp_path / bootstrap.PLAN_NAME).write_text(
        json.dumps({
            "hardware": profile.as_dict(),
            "ocr_backend": "deepseek-rocm",
            "vsr_backend": "video-subtitle-remover",
        }),
        encoding="utf-8",
    )

    assert bootstrap.ensure_hardware_plan().ocr_backend == "paddleocr"

def test_linux_bootstrap_does_not_offer_ffmpeg_download(monkeypatch):
    monkeypatch.setattr(bootstrap.sys, "platform", "linux")

    assert "ffmpeg" not in [step.key for step in bootstrap.steps()]
