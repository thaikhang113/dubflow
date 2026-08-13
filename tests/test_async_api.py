import asyncio
import sys
import threading

import pytest

from autodub.async_subprocess import run_async_process
from autodub.config import Settings
from autodub.pipeline import DubPipeline
from autodub.providers.openai_compatible import OpenAICompatibleProvider


def test_pipeline_run_async_delegates_to_sync_run(monkeypatch):
    pipeline = DubPipeline(Settings())
    expected = object()

    def fake_run(request):
        return expected

    monkeypatch.setattr(pipeline, "run", fake_run)

    assert asyncio.run(pipeline.run_async(object())) is expected


def test_pipeline_run_async_preserves_cancellation(monkeypatch):
    pipeline = DubPipeline(Settings())
    cancel_seen = threading.Event()

    def fake_run(request):
        cancel_seen.set()
        raise RuntimeError("cancelled")

    monkeypatch.setattr(pipeline, "run", fake_run)

    with pytest.raises(RuntimeError, match="cancelled"):
        asyncio.run(pipeline.run_async(object()))
    assert cancel_seen.is_set()


def test_provider_async_methods_use_same_sync_results(monkeypatch):
    provider = OpenAICompatibleProvider(
        "https://example.test/v1", "secret", model="model")
    monkeypatch.setattr(provider, "list_models", lambda: ["model"])
    monkeypatch.setattr(provider, "check_model", lambda: None)
    monkeypatch.setattr(provider, "translate", lambda *args, **kwargs: [{"id": 1}])

    async def check():
        assert await provider.list_models_async() == ["model"]
        assert await provider.check_model_async() is None
        assert await provider.translate_async([{"id": 1}]) == [{"id": 1}]

    asyncio.run(check())


def test_async_subprocess_returns_output():
    result = asyncio.run(run_async_process(
        sys.executable, "-c", "print('ok')"))

    assert result.returncode == 0
    assert result.stdout.strip() == "ok"


def test_async_subprocess_timeout():
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(run_async_process(
            sys.executable, "-c", "import time; time.sleep(30)",
            timeout=0.01))
