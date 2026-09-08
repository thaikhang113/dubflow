"""Mỗi bước pipeline phải phát "start" rồi "done"/"skip"/"error".

Giao diện dựa vào cặp sự kiện này: ``run_state.step_percent`` chỉ cộng trọng số
khi bước được đánh dấu xong, ``Narrator`` chỉ in dòng "Đang …" khi có ``start``,
và mọi tự động hóa bấm Dừng theo bước đều cần ``start``. Thiếu ``start`` ở bước
dài nhất (TTS) nghĩa là người dùng không bao giờ thấy bước đó sáng lên.
"""
from __future__ import annotations

import inspect

import pytest

from autodub.progress import STEPS

SOURCE = inspect.getsource(
    __import__("autodub.pipeline", fromlist=["DubPipeline"]))


def _emitted(step: str, status: str) -> bool:
    return f'rep.emit("{step}", "{status}"' in SOURCE


@pytest.mark.parametrize("step", [s for s in STEPS if s != "done"])
def test_every_step_emits_start(step: str) -> None:
    assert _emitted(step, "start"), (
        f"bước {step!r} không phát 'start' — giao diện sẽ không bao giờ báo "
        "đang chạy bước này")


@pytest.mark.parametrize("step", [s for s in STEPS if s != "done"])
def test_every_step_has_a_terminal_event(step: str) -> None:
    terminal = any(_emitted(step, s)
                   for s in ("done", "skip", "error", "warning"))
    assert terminal, f"bước {step!r} không có sự kiện kết thúc nào"


def test_tts_step_announces_itself_before_the_longest_wait() -> None:
    """Hồi quy: TTS chỉ phát progress/done, không phát start.

    TTS chiếm 30/100 trọng số tiến trình — im lặng ở bước này khiến thanh tiến
    trình đứng yên gần như cả lượt chạy.
    """
    assert _emitted("tts", "start")
