from autodub.worker_plan import build_worker_plan


def test_auto_worker_plan_caps_low_memory_machine():
    plan = build_worker_plan(
        mode="auto",
        cpu_count=16,
        available_ram_gb=2.0,
        gpu_available=False,
        configured={"tts": 7, "parallel": 10, "asr": 16},
    )

    assert plan["tts"]["effective"] == 1
    assert plan["parallel"]["effective"] == 1
    assert plan["asr"]["effective"] == 1


def test_manual_worker_plan_still_respects_safe_caps():
    plan = build_worker_plan(
        mode="manual",
        cpu_count=16,
        available_ram_gb=4.0,
        gpu_available=False,
        configured={"tts": 7, "parallel": 10, "asr": 16},
    )

    assert plan["tts"]["requested"] == 7
    assert plan["tts"]["effective"] == 2
    assert plan["parallel"]["effective"] == 2


def test_auto_worker_plan_uses_cpu_and_gpu_capacity():
    plan = build_worker_plan(
        mode="auto",
        cpu_count=16,
        available_ram_gb=12.0,
        gpu_available=True,
        configured={"tts": 7, "parallel": 10, "asr": 16},
    )

    assert plan["tts"]["effective"] == 6
    assert plan["parallel"]["effective"] == 8
    assert plan["asr"]["effective"] == 4
    assert plan["ocr"]["effective"] == 1
    assert plan["demucs"]["effective"] == 1


def test_auto_mode_ignores_stale_manual_worker_values():
    plan = build_worker_plan(
        mode="auto",
        cpu_count=16,
        available_ram_gb=12.0,
        gpu_available=False,
        configured={"tts": 1, "parallel": 1, "asr": 1},
    )

    assert plan["tts"]["effective"] == 6
    assert plan["parallel"]["effective"] == 8
    assert plan["asr"]["effective"] == 4


def test_auto_worker_plan_uses_safe_default_when_ram_is_unknown():
    plan = build_worker_plan(
        mode="auto",
        cpu_count=16,
        available_ram_gb=None,
        gpu_available=False,
    )

    assert plan["tts"]["effective"] == 3
