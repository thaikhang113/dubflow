from autodub.pipeline import DubPipeline


def test_machine_info_returns_worker_plan(monkeypatch):
    monkeypatch.setattr("autodub.sysinfo.total_ram_gb", lambda: 16.0)
    monkeypatch.setattr("autodub.sysinfo.available_ram_gb", lambda: 2.0)
    monkeypatch.setattr("autodub.media.vocal_separator.gpu_venv_python",
                        lambda: "")
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
