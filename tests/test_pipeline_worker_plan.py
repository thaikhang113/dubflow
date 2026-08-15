from autodub.pipeline import DubPipeline


def test_machine_info_returns_worker_plan(monkeypatch):
    monkeypatch.setattr("autodub.sysinfo.total_ram_gb", lambda: 16.0)
    monkeypatch.setattr("autodub.sysinfo.available_ram_gb", lambda: 2.0)
    monkeypatch.setattr("autodub.media.vocal_separator.gpu_venv_python",
                        lambda: "")
    monkeypatch.setattr(
        "autodub.gpu.detect_gpu",
        lambda: type("GPUInfo", (), {
            "label": "CPU fallback",
            "compute_available": False,
        })(),
    )
    monkeypatch.setattr("autodub.media.video.video_encoder_name",
                        lambda: "CPU")

    settings = type("Settings", (), {
        "worker_mode": "auto",
        "vieneu_max_workers": 7,
        "parallel_workers": 10,
        "asr_num_threads": 16,
    })()
    plan = DubPipeline._log_machine_info(settings)
    assert plan["tts"]["effective"] == 1
    assert plan["parallel"]["effective"] == 1


def test_machine_info_accepts_non_cuda_gpu_runtime(monkeypatch):
    monkeypatch.setattr("autodub.sysinfo.total_ram_gb", lambda: 16.0)
    monkeypatch.setattr("autodub.sysinfo.available_ram_gb", lambda: 12.0)
    monkeypatch.setattr("autodub.media.vocal_separator.gpu_venv_python",
                        lambda: "")
    monkeypatch.setattr(
        "autodub.gpu.detect_gpu",
        lambda: type("GPUInfo", (), {
            "label": "AMD Radeon (ROCm)",
            "compute_available": True,
        })(),
    )
    monkeypatch.setattr("autodub.media.video.video_encoder_name",
                        lambda: "AMD AMF")

    settings = type("Settings", (), {
        "worker_mode": "auto",
        "vieneu_max_workers": 3,
        "parallel_workers": 2,
        "asr_num_threads": 4,
    })()
    plan = DubPipeline._log_machine_info(settings)

    assert plan["gpu"]["available"] is True
