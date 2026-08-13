"""Async subprocess helpers for callers with an asyncio event loop."""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass


@dataclass
class AsyncProcessResult:
    returncode: int
    stdout: str
    stderr: str


async def run_async_process(
    *args: str,
    timeout: float | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> AsyncProcessResult:
    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=getattr(subprocess_constants, "CREATE_NO_WINDOW", 0),
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    return AsyncProcessResult(
        process.returncode or 0,
        stdout.decode(errors="replace"),
        stderr.decode(errors="replace"),
    )


try:
    import subprocess as subprocess_constants
except ImportError:  # pragma: no cover
    subprocess_constants = os
