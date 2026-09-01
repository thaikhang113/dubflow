"""Small retry and artifact helpers shared by model installers."""
from __future__ import annotations

import json
import os
import sys
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

def find_bundled_worker(relative: str, project_root: str) -> str:
    """Find worker in source, PyInstaller data, or installed app layout."""
    roots = [
        os.environ.get("DUBFLOW_APP_ROOT", ""),
        os.environ.get("DUBFLOW_DATA_DIR", ""),
        project_root,
        os.path.dirname(os.path.abspath(__file__)),
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        os.path.dirname(os.path.abspath(sys.executable)),
        getattr(sys, "_MEIPASS", ""),
    ]
    suffixes = (
        "",
        "data",
        "_internal",
        os.path.join("_internal", "data"),
        os.path.join("data", "_internal"),
        "resources",
    )
    for root in dict.fromkeys(
        os.path.abspath(path) for path in roots if path and os.path.isdir(path)
    ):
        for suffix in suffixes:
            candidate = os.path.join(root, suffix, relative)
            if os.path.isfile(candidate):
                return candidate
    return ""


def smoke_request(audio_path: str) -> str:
    return json.dumps({"audio": str(audio_path)}, ensure_ascii=False) + "\n"
