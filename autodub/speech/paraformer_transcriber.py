"""Paraformer ASR driver — runs the worker in .venv-asr as a one-shot subprocess.

Unlike the TTS engines (hundreds of small requests → persistent worker pool),
ASR is one request per pipeline run, so the worker starts, streams one JSON
line per recognized segment (progress shows up in the GUI log live) and exits.

The worker script (:mod:`autodub.speech.asr_paraformer_worker`) is standalone
and executes with the .venv-asr interpreter — sherpa-onnx never has to be
installed in (or bundled with) the main app.
"""
from __future__ import annotations

import json
import subprocess
import threading
from collections import deque

from autodub.config import Settings
from autodub.utils import bundled_file, setup_logging

logger = setup_logging("autodub.paraformer")

_WORKER_SCRIPT = bundled_file("autodub", "speech", "asr_paraformer_worker.py")


def transcribe_paraformer(audio_path: str, settings: Settings) -> list[dict]:
    """Run the Paraformer worker on ``audio_path`` (16 kHz mono WAV).

    Returns Whisper-shaped segments ``[{id, text, start, end, duration}]``.
    Raises :class:`RuntimeError` on any failure — the caller falls back to
    Whisper.
    """
    cmd = [
        settings.asr_venv_python_path(),
        _WORKER_SCRIPT,
        "--audio", audio_path,
        "--model-dir", settings.paraformer_model_dir_path(),
        "--num-threads", str(settings.asr_num_threads),
    ]
    logger.info("Nhận dạng tiếng Trung bằng Paraformer (sherpa-onnx, CPU)...")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )

    stderr_tail: deque[str] = deque(maxlen=20)

    def _drain() -> None:
        try:
            for line in proc.stderr:
                line = line.rstrip()
                if line:
                    stderr_tail.append(line)
        except (ValueError, OSError):
            pass

    threading.Thread(target=_drain, daemon=True).start()

    segments: list[dict] = []
    done = False
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("error"):
                raise RuntimeError(f"Paraformer worker: {msg['error']}")
            if msg.get("seg"):
                start = float(msg["start"])
                end = float(msg["end"])
                segments.append({
                    "id": len(segments) + 1,
                    "text": str(msg["text"]).strip(),
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "duration": round(end - start, 3),
                })
                logger.info(f"Segment {len(segments)}: "
                            f"[{start:.1f}s-{end:.1f}s] {msg['text'][:50]}...")
            elif msg.get("done"):
                done = True
        # Thời lượng phụ thuộc độ dài video — chờ tiến trình kết thúc hẳn
        # (stdout đã EOF nên wait không thể treo vô hạn vì pipe đầy).
        proc.wait(timeout=600)
    finally:
        if proc.poll() is None:
            proc.kill()
        for s in (proc.stdout, proc.stderr):
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass

    tail = "\n".join(stderr_tail)
    if not done:
        raise RuntimeError(
            f"Paraformer worker thoát bất thường (exit {proc.returncode})"
            + (f"\n{tail}" if tail else ""))
    if not segments:
        raise RuntimeError("Paraformer không nhận dạng được câu nào"
                           + (f"\n{tail}" if tail else ""))
    return segments
