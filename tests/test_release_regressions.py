"""Regression gates for translation resume and the local HTTP bridge."""
from __future__ import annotations

import json
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from autodub.config import Settings
from autodub.languages import get_target
from autodub.openclaw_runtime import OpenClawRuntime
from autodub.pipeline import DubPipeline, DubRequest
from autodub.pipeline_state import load_pipeline_state
from autodub.providers.openai_compatible import OpenAICompatibleError
from autodub.worker_plan import build_worker_plan
from tests.test_openclaw_runtime import _request


SEGMENTS = [
    {"id": 1, "text": "hello", "start": 0.0, "end": 2.0, "duration": 2.0},
]


@pytest.fixture
def translation_endpoint():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            calls.append({
                "authorization": self.headers.get("Authorization"),
                "payload": json.loads(self.rfile.read(
                    int(self.headers["Content-Length"]))),
            })
            body = json.dumps({"choices": [{"message": {"content": json.dumps({
                "segments": [{"id": 1, "text_vi": "Xin chao."}],
            })}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_pipeline_translates_with_keyless_local_endpoint(translation_endpoint):
    endpoint, calls = translation_endpoint
    pipeline = DubPipeline(Settings(
        translation_endpoint=endpoint, translation_model="local",
        translation_api_key="", translate_enabled=True,
    ))
    result = pipeline._auto_translate(SEGMENTS, get_target("vi"), "en")
    assert result[0]["text_vi"] == "Xin chao."
    assert len(calls) == 1
    assert calls[0]["authorization"] is None


def test_translation_programming_error_is_not_manual_pending(monkeypatch):
    pipeline = DubPipeline(Settings())

    def broken(*_args, **_kwargs):
        raise TypeError("invalid internal segment")

    monkeypatch.setattr(pipeline, "_auto_translate", broken)
    with pytest.raises(TypeError, match="internal segment"):
        pipeline._try_auto_translate(
            SEGMENTS, get_target("vi"), DubRequest(), "unused",
        )


@pytest.mark.parametrize("payload", [
    [],
    {"links": 42},
    {"links": ["https://example.com/video"], "options": []},
    {"links": ["https://example.com/video"], "options": {"branding": []}},
])
def test_openclaw_bad_input_returns_400(tmp_path, payload):
    runtime = OpenClawRuntime(data_dir=tmp_path)
    runtime.start(worker=False)
    try:
        status, body = _request(
            runtime.endpoint + "/v1/prepare", runtime.token, "POST", payload,
        )
        assert status == 400
        assert body["ok"] is False
        assert not list(runtime.queue_root.rglob("*.json"))
    finally:
        runtime.stop()


@pytest.fixture
def cached_pipeline(tmp_path, monkeypatch):
    work = tmp_path / "video_vi"
    data = work / "data"
    data.mkdir(parents=True)
    source = work / "source.mp4"
    source.write_bytes(b"cached source")
    (data / "original_audio.wav").write_bytes(b"cached audio")
    (data / "transcript_original.json").write_text(
        json.dumps(SEGMENTS), encoding="utf-8",
    )
    settings = Settings(
        translate_enabled=False, hq_background=False,
        ocr_enabled=False, branding_vision_enabled=False,
    )
    pipeline = DubPipeline(settings)
    monkeypatch.setattr(pipeline, "_log_machine_info", lambda _settings:
                        build_worker_plan(
                            cpu_count=2, available_ram_gb=4,
                            gpu_available=False,
                        ))
    monkeypatch.setattr(pipeline, "_warm_tts_early", lambda *_args: None)
    monkeypatch.setattr(pipeline, "_get_synth", lambda *_args: None)
    request = DubRequest(
        file_path=str(source), resume_dir=str(work), bg_mode="none",
        source_lang="en",
    )
    return pipeline, request, data


@pytest.mark.parametrize("endpoint_failed", [False, True])
def test_manual_pending_is_persisted_and_asr_is_preserved(
    cached_pipeline, monkeypatch, endpoint_failed,
):
    pipeline, request, data = cached_pipeline
    before = (data / "transcript_original.json").read_bytes()
    if endpoint_failed:
        def unavailable(*_args, **_kwargs):
            raise OpenAICompatibleError("endpoint unavailable")

        monkeypatch.setattr(pipeline, "_auto_translate", unavailable)
    result = pipeline.run(request)
    assert result.status == "translate_pending"
    state = load_pipeline_state(result.work_dir)
    assert state["pipeline"]["status"] == "translate_pending"
    assert (data / "transcript_original.json").read_bytes() == before
    assert (data.parent / "TRANSLATE_PENDING.txt").is_file()


def test_translation_checkpoint_survives_failed_transcript_save(
    cached_pipeline, translation_endpoint, monkeypatch,
):
    from autodub.speech import transcriber

    pipeline, request, data = cached_pipeline
    endpoint, calls = translation_endpoint
    pipeline.settings = replace(
        pipeline.settings, translate_enabled=True,
        translation_endpoint=endpoint, translation_api_key="",
        translation_model="local",
    )
    save = transcriber.save_transcript

    def disk_full(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(transcriber, "save_transcript", disk_full)
    with pytest.raises(OSError, match="disk full"):
        pipeline.run(request)
    checkpoint = data / "translate_checkpoint.json"
    assert checkpoint.is_file()
    assert not (data / "transcript_vi.json").exists()

    monkeypatch.setattr(transcriber, "save_transcript", save)

    def stop_at_tts(*_args, **_kwargs):
        raise RuntimeError("reached TTS")

    monkeypatch.setattr(pipeline, "_synthesize_segments", stop_at_tts)
    with pytest.raises(RuntimeError, match="reached TTS"):
        pipeline.run(request)
    assert len(calls) == 1
    assert json.loads((data / "transcript_vi.json").read_text(
        encoding="utf-8"))[0]["text_vi"] == "Xin chao."
    assert not checkpoint.exists()


def test_manual_translation_resume_reuses_asr_and_removes_hint(
    cached_pipeline, monkeypatch,
):
    pipeline, request, data = cached_pipeline
    pipeline.run(request)
    original = (data / "transcript_original.json").read_bytes()
    (data / "transcript_vi.json").write_text(
        json.dumps([{**SEGMENTS[0], "text_vi": "Xin chao."}]),
        encoding="utf-8",
    )

    def stop_at_tts(*_args, **_kwargs):
        raise RuntimeError("reached TTS")

    monkeypatch.setattr(pipeline, "_synthesize_segments", stop_at_tts)
    with pytest.raises(RuntimeError, match="reached TTS"):
        pipeline.run(request)
    assert (data / "transcript_original.json").read_bytes() == original
    assert not (data.parent / "TRANSLATE_PENDING.txt").exists()
