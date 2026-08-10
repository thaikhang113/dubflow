"""Bước dịch phải sống qua lỗi mạng tạm thời, và không vượt trần nhịp gửi.

Đây là bài học từ lỗi thật: lần chạy đầu hay chết ở bước dịch vì một cú chớp
mạng, chạy lại mới xong (server trả cache theo ``job_id``). Retry ở đây làm lần
đầu cũng xong — và vì ``job_id`` băm theo nội dung lô nên gửi lại không tốn Vox.
"""
from __future__ import annotations

import threading

import pytest

from autodub.config import Settings
from autodub.languages import get_target
from autodub.saas_client import (
    DeviceBlockedError,
    InsufficientCreditError,
    OfflineError,
    SaasError,
)
from autodub.text import translate_saas
from autodub.text.translate_common import TranslateError

SEGMENTS = [
    {"id": 1, "text": "hello", "duration": 2.0, "slot": 2.0},
    {"id": 2, "text": "world", "duration": 2.0, "slot": 2.0},
]


class FakeClient:
    """Máy khách giả: ném theo kịch bản rồi trả kết quả hợp lệ."""

    def __init__(self, errors: list[BaseException]):
        self.errors = list(errors)
        self.job_ids: list[str] = []

    def translate(self, segments, *, job_id, **kwargs):
        self.job_ids.append(job_id)
        if self.errors:
            raise self.errors.pop(0)
        return {
            "segments": [{"id": s["id"], "text_vi": f"vi {s['text']}"}
                         for s in segments],
            "creditCharged": len(segments),
            "balanceAfter": 100,
        }


@pytest.fixture
def patched(monkeypatch):
    """Bỏ chờ thật và bỏ chặn nhịp — test chỉ quan tâm số lượt gọi."""
    monkeypatch.setattr(translate_saas, "_sleep_cancellable",
                        lambda delay, reporter, stop: None)
    monkeypatch.setattr(translate_saas.RATE_LIMITER, "acquire", lambda: None)


def _run(client, monkeypatch):
    monkeypatch.setattr(translate_saas, "get_client", lambda: client)
    return translate_saas.translate_segments(
        [dict(s) for s in SEGMENTS], get_target("vi"), "zh", Settings())


def test_transient_network_error_is_retried(patched, monkeypatch):
    client = FakeClient([OfflineError("mất mạng"), OfflineError("mất mạng")])
    out = _run(client, monkeypatch)
    assert len(client.job_ids) == 3
    assert out[0]["text_vi"] == "vi hello"


def test_retry_reuses_the_same_job_id(patched, monkeypatch):
    """Cùng job_id giữa các lượt = máy chủ không trừ Vox lần hai."""
    client = FakeClient([OfflineError("mất mạng")])
    _run(client, monkeypatch)
    assert len(set(client.job_ids)) == 1


def test_rate_limited_is_retried(patched, monkeypatch):
    client = FakeClient([SaasError("bận", code="RATE_LIMITED", status=429)])
    _run(client, monkeypatch)
    assert len(client.job_ids) == 2


def test_server_error_is_retried(patched, monkeypatch):
    client = FakeClient([SaasError("sập", status=503)])
    _run(client, monkeypatch)
    assert len(client.job_ids) == 2


def test_gives_up_after_max_attempts(patched, monkeypatch):
    client = FakeClient([OfflineError("mất mạng")] * translate_saas._MAX_ATTEMPTS)
    with pytest.raises(TranslateError):
        _run(client, monkeypatch)
    assert len(client.job_ids) == translate_saas._MAX_ATTEMPTS


def test_out_of_credit_is_not_retried(patched, monkeypatch):
    client = FakeClient([InsufficientCreditError("hết Vox")])
    with pytest.raises(InsufficientCreditError):
        _run(client, monkeypatch)
    assert len(client.job_ids) == 1


def test_device_blocked_is_not_retried(patched, monkeypatch):
    client = FakeClient([DeviceBlockedError("bị khóa", code="DEVICE_BLOCKED")])
    with pytest.raises(TranslateError):
        _run(client, monkeypatch)
    assert len(client.job_ids) == 1


def test_client_error_is_not_retried(patched, monkeypatch):
    client = FakeClient([SaasError("sai yêu cầu", status=400)])
    with pytest.raises(TranslateError):
        _run(client, monkeypatch)
    assert len(client.job_ids) == 1


# ------------------------------------------------------------ chặn nhịp ----

def test_rate_limiter_admits_up_to_the_limit_then_waits():
    limiter = translate_saas._RateLimiter(limit=3, window_s=60.0)
    clock = [0.0]
    slept: list[float] = []

    def fake_sleep(s):
        slept.append(s)
        clock[0] += s

    for _ in range(3):
        limiter.acquire(sleep=fake_sleep, now=lambda: clock[0])
    assert slept == []          # ba lượt đầu đi ngay

    limiter.acquire(sleep=fake_sleep, now=lambda: clock[0])
    assert slept                # lượt thứ tư phải chờ
    assert clock[0] >= 60.0     # tới khi mốc cũ nhất rời cửa sổ


def test_rate_limiter_is_shared_across_threads():
    """Trần là của THIẾT BỊ — mỗi luồng tự đếm thì tổng vẫn vượt."""
    limiter = translate_saas._RateLimiter(limit=5, window_s=60.0)
    live = [0]
    peak = [0]
    guard = threading.Lock()

    def worker():
        limiter.acquire(sleep=lambda s: None, now=lambda: 0.0)
        with guard:
            live[0] += 1
            peak[0] = max(peak[0], live[0])

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak[0] == 5
    assert len(limiter._hits) == 5


def test_retry_after_header_wins_over_backoff(monkeypatch):
    """Máy chủ nói chờ bao lâu thì nghe máy chủ, nếu lâu hơn giãn cách mặc định."""
    waited: list[float] = []
    monkeypatch.setattr(translate_saas, "_sleep_cancellable",
                        lambda delay, reporter, stop: waited.append(delay))
    monkeypatch.setattr(translate_saas.RATE_LIMITER, "acquire", lambda: None)
    client = FakeClient([SaasError("bận", code="RATE_LIMITED", status=429,
                                   retry_after=42.0)])
    _run(client, monkeypatch)
    assert waited == [42.0]
