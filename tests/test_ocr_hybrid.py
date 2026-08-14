from types import SimpleNamespace

from autodub.media import ocr
from autodub.media.deepseek_ocr_worker import _frames as deepseek_frames
from autodub.media.deepseek_ocr_worker import parse_grounding
from autodub.media.ocr_worker import _frames as paddle_frames


def _settings(tmp_path, *, enabled=True, backend="hybrid"):
    return SimpleNamespace(
        ocr_backend=backend,
        deepseek_ocr_enabled=enabled,
        ocr_sample_interval=1.0,
        ocr_min_confidence=0.8,
        ocr_max_region_area=0.25,
        ocr_subtitle_y_min=0.65,
        ocr_venv_python_path=lambda: str(tmp_path / "paddle-python"),
        ocr_model_dir_path=lambda: str(tmp_path / "paddle-model"),
        ocr_configured=lambda: True,
        deepseek_ocr_configured=lambda: True,
        deepseek_ocr_venv_python_path=lambda: str(tmp_path / "deepseek-python"),
        deepseek_ocr_model_dir_path=lambda: str(tmp_path / "deepseek-model"),
    )


def test_hybrid_uses_deepseek_when_paddle_has_no_valid_regions(
    monkeypatch, tmp_path
):
    calls = []

    def fake_worker(video_path, duration, settings, *, backend):
        calls.append(backend)
        if backend == "paddle":
            return []
        return [{
            "text": "中文字幕",
            "confidence": 0.9,
            "box": [[100, 700], [500, 700], [500, 760], [100, 760]],
            "time": 0.0,
        }]

    monkeypatch.setattr(ocr, "_run_engine_detections", fake_worker)
    subtitle, logo = ocr.detect_regions_with_logo(
        "video.mp4", 1000, 1000, 2.0, _settings(tmp_path)
    )

    assert calls == ["paddle", "deepseek"]
    assert subtitle and subtitle[0]["source"] == "ocr"
    assert logo == []


def test_hybrid_does_not_call_deepseek_when_disabled(monkeypatch, tmp_path):
    calls = []

    def fake_worker(video_path, duration, settings, *, backend):
        calls.append(backend)
        return [{
            "text": "中文字幕",
            "confidence": 0.9,
            "box": [[100, 700], [500, 700], [500, 760], [100, 760]],
            "time": 0.0,
        }]

    monkeypatch.setattr(ocr, "_run_engine_detections", fake_worker)
    ocr.detect_regions_with_logo(
        "video.mp4", 1000, 1000, 2.0,
        _settings(tmp_path, enabled=False),
    )

    assert calls == ["paddle"]


def test_non_hybrid_backend_keeps_paddle_only(monkeypatch, tmp_path):
    calls = []

    def fake_worker(video_path, duration, settings, *, backend):
        calls.append(backend)
        return []

    monkeypatch.setattr(ocr, "_run_engine_detections", fake_worker)
    ocr.detect_regions_with_logo(
        "video.mp4", 1000, 1000, 2.0,
        _settings(tmp_path, backend="paddle"),
    )

    assert calls == ["paddle"]


def test_hybrid_falls_back_when_paddle_worker_fails(monkeypatch, tmp_path):
    calls = []

    def fake_worker(video_path, duration, settings, *, backend):
        calls.append(backend)
        if backend == "paddle":
            raise RuntimeError("Paddle missing")
        return [{
            "text": "中文字幕",
            "confidence": 0.9,
            "box": [[100, 700], [500, 700], [500, 760], [100, 760]],
            "time": 0.0,
        }]

    monkeypatch.setattr(ocr, "_run_engine_detections", fake_worker)
    subtitle, _ = ocr.detect_regions_with_logo(
        "video.mp4", 1000, 1000, 2.0, _settings(tmp_path)
    )

    assert calls == ["paddle", "deepseek"]
    assert subtitle


def test_deepseek_grounding_parser_returns_shared_box_schema():
    detections = parse_grounding(
        "<|ref|>中文字幕<|/ref|><|det|>[[100, 700, 500, 760]]<|/det|>",
        1000,
        1000,
        1.5,
    )

    assert detections == [{
        "text": "中文字幕",
        "confidence": 0.85,
        "box": [[100.0, 700.0], [500.0, 700.0],
                [500.0, 760.0], [100.0, 760.0]],
        "time": 1.5,
    }]


def test_deepseek_grounding_parser_rejects_invalid_boxes():
    assert parse_grounding(
        "<|ref|>x<|/ref|><|det|>[[10, 10, 10, 20]]<|/det|>",
        1000,
        1000,
        0.0,
    ) == []


def test_ocr_frame_extractors_avoid_unsupported_vsync(monkeypatch, tmp_path):
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        for index in range(1, 3):
            (tmp_path / f"{index:05d}.png").write_bytes(b"png")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    assert len(paddle_frames("video.mp4", [0.0, 1.0], str(tmp_path))) == 2
    assert len(deepseek_frames("video.mp4", [0.0, 1.0], str(tmp_path))) == 2
    assert all("-vsync" not in command for command in commands)
