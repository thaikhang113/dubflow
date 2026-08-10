"""Small retry and artifact helpers shared by model installers."""
from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")


def retry_call(
    operation: Callable[[], T],
    attempts: int = 3,
    delay: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    last: BaseException | None = None
    for index in range(max(1, attempts)):
        try:
            return operation()
        except BaseException as exc:
            last = exc
            if index + 1 < max(1, attempts):
                sleep(delay * (2 ** index))
    assert last is not None
    raise last


def is_nonempty_file(path: str | os.PathLike[str]) -> bool:
    try:
        return Path(path).is_file() and Path(path).stat().st_size > 0
    except OSError:
        return False
