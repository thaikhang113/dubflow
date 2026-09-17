"""Mock OpenAI-compatible server for the translation step.

The endpoint configured in .env is unreachable from this machine, so the real
API code path would never be exercised. This mock answers /v1/models and
/v1/chat/completions well enough to drive autodub end to end: it reads the
segment array embedded in the prompt and returns Vietnamese text sized to the
per-segment max_chars budget.

Kept ASCII-only on purpose: this file is a test harness, and non-ASCII literals
here have already been mangled once by an editor round-trip.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VI_SENTENCE = (
    "d\u00e2y l\u00e0 b\u1ea3n d\u1ecbch gi\u1ea3 l\u1eadp "
    "\u0111\u1ec3 ki\u1ec3m tra pipeline"
)


def extract_segments(prompt: str) -> list[dict]:
    """Return the largest JSON array of objects that all carry an "id" key.

    Matching on structure instead of on the Vietnamese label keeps the harness
    independent of source-file encoding.
    """
    best: list[dict] = []
    for start in (i for i, ch in enumerate(prompt) if ch == "["):
        depth = 0
        for end in range(start, len(prompt)):
            ch = prompt[end]
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(prompt[start:end + 1])
                    except json.JSONDecodeError:
                        break
                    if (isinstance(data, list) and data
                            and all(isinstance(d, dict) and "id" in d
                                    for d in data)
                            and len(data) > len(best)):
                        best = data
                    break
    return best


def fake_vi(max_chars: int | None) -> str:
    """Vietnamese-looking sentence that respects the character budget."""
    base = VI_SENTENCE
    if max_chars and max_chars > 0:
        # Reserve one slot for the terminal period so the result never exceeds
        # the budget the pipeline asked for (an over-budget mock reply would
        # look like a product bug instead of a harness artefact).
        base = (base + " " + base)[:max(1, max_chars - 1)].rstrip()
    return base if base.endswith(".") else base + "."


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args) -> None:
        return

    def _send(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.rstrip("/").endswith("/models"):
            self._send({"data": [{"id": "mock-vi", "object": "model"}]})
            return
        self._send({"error": "not found"}, 404)

    def do_POST(self):  # noqa: N802
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._send({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, OSError):
            self._send({"error": "bad request"}, 400)
            return
        messages = request.get("messages") or []
        user = next((m.get("content", "") for m in messages
                     if m.get("role") == "user"), "")
        segments = [
            {"id": seg.get("id"), "text_vi": fake_vi(seg.get("max_chars"))}
            for seg in extract_segments(user)
        ]
        content = json.dumps({"segments": segments}, ensure_ascii=False)
        self._send({
            "id": "mock", "object": "chat.completion",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant",
                                     "content": content}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                      "total_tokens": 2},
        })


class MockTranslate:
    """Bind an ephemeral loopback port, serve in a daemon thread, clean stop."""

    def __init__(self) -> None:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._thread: threading.Thread | None = None
        self.port = self._server.server_address[1]

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def start(self) -> "MockTranslate":
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True,
            name="mock-translate")
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
