"""App-managed local HTTP bridge for OpenClaw."""
from __future__ import annotations

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

from autodub.config import Settings
from autodub.remote_worker import run_worker
from autodub.utils import data_root

_MAX_BODY = 1_000_000
_DEFAULT_BIND_HOST = "0.0.0.0"
_DEFAULT_PORT = 38643
_DOCKER_HOST = "host.docker.internal"


class _Server(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, runtime, address):
        super().__init__(address, _Handler)
        self.runtime = runtime


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def log_message(self, _format, *_args) -> None:
        return

    def _reply(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        value = self.headers.get("Authorization", "")
        return secrets.compare_digest(
            value.removeprefix("Bearer ").strip(),
            self.server.runtime.token,
        )

    def _json_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Content-Length không hợp lệ") from exc
        if length <= 0 or length > _MAX_BODY:
            raise ValueError("Request quá lớn hoặc rỗng")
        raw = self.rfile.read(length)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Request phải là object JSON")
        return payload

    def _dispatch(self, method: str) -> None:
        runtime = self.server.runtime
        if not self._authorized():
            self._reply(401, {"ok": False, "error": "Token không hợp lệ"})
            return

        path = urlsplit(self.path).path.rstrip("/") or "/"
        try:
            if method == "GET" and path == "/health":
                self._reply(200, {"ok": True, "service": "dubflow-openclaw"})
                return

            if method == "GET" and path.startswith("/v1/batches/"):
                batch_id = path.removeprefix("/v1/batches/")
                if "/" in batch_id or not batch_id:
                    raise ValueError("batch_id không hợp lệ")
                result = runtime.handle(
                    {"action": "status", "batch_id": batch_id})
                self._reply(200, result)
                return

            if method == "POST" and path in ("/v1/prepare", "/v1/submit"):
                payload = self._json_body()
                payload["action"] = path.rsplit("/", 1)[-1]
                self._reply(200, runtime.handle(payload))
                return

            if method == "POST" and path.startswith("/v1/batches/"):
                parts = path.split("/")
                if len(parts) != 5:
                    raise ValueError("Đường dẫn batch không hợp lệ")
                batch_id, operation = parts[3], parts[4]
                action = {
                    "cancel": "cancel",
                    "retry-failed": "retry_failed",
                }.get(operation)
                if not action:
                    self._reply(404, {"ok": False, "error": "Route không tồn tại"})
                    return
                self._reply(200, runtime.handle(
                    {"action": action, "batch_id": batch_id}))
                return

            self._reply(404, {"ok": False, "error": "Route không tồn tại"})
        except (ValueError, FileNotFoundError) as exc:
            self._reply(400, {"ok": False, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            self._reply(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")


class OpenClawRuntime:
    """Owns local OpenClaw API and its persistent processing queue."""

    def __init__(self, settings_provider=None, *, data_dir: str | Path | None = None):
        self._data_dir = Path(data_dir or data_root()).expanduser().resolve()
        self._queue_root = self._data_dir / "openclaw_queue"
        self._config_path = self._data_dir / "openclaw.json"
        config = self._read_config()
        self._enabled = bool(config.get("enabled", False))
        self._token = str(config.get("token") or secrets.token_urlsafe(32))
        self._bind_host = str(
            config.get("bind_host") or _DEFAULT_BIND_HOST).strip()
        try:
            self._port = int(config.get("port", _DEFAULT_PORT))
        except (TypeError, ValueError):
            self._port = _DEFAULT_PORT
        if not 1 <= self._port <= 65535:
            self._port = _DEFAULT_PORT
        self._settings_provider = settings_provider or (
            lambda: Settings.load(override=True))
        self._server: _Server | None = None
        self._server_thread: threading.Thread | None = None
        self._worker_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._write_config()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def running(self) -> bool:
        return (self._server_thread is not None
                and self._server_thread.is_alive())

    @property
    def token(self) -> str:
        return self._token

    @property
    def endpoint(self) -> str:
        if self._server is None:
            return ""
        _host, port = self._server.server_address
        return f"http://127.0.0.1:{port}"

    @property
    def docker_endpoint(self) -> str:
        if self._server is None:
            return ""
        _host, port = self._server.server_address
        return f"http://{_DOCKER_HOST}:{port}"

    @property
    def queue_root(self) -> Path:
        return self._queue_root

    def _read_config(self) -> dict:
        try:
            value = json.loads(self._config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _write_config(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        temp = self._config_path.with_suffix(".json.part")
        temp.write_text(json.dumps(
            {"enabled": self._enabled, "token": self._token,
             "bind_host": self._bind_host, "port": self._port},
            ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self._config_path)

    def start(self, *, worker: bool = True) -> None:
        with self._lock:
            if self.running:
                return
            self._queue_root.mkdir(parents=True, exist_ok=True)
            self._stop_event.clear()
            self._server = _Server(self, (self._bind_host, self._port))
            self._server_thread = threading.Thread(
                target=self._server.serve_forever,
                name="dubflow-openclaw-api",
                daemon=True,
            )
            self._server_thread.start()
            if worker:
                self._worker_thread = threading.Thread(
                    target=run_worker,
                    args=(str(self._queue_root),
                          self._settings_provider(),
                          self._stop_event),
                    name="dubflow-openclaw-worker",
                    daemon=True,
                )
                self._worker_thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stop_event.set()
            if self._server is not None:
                self._server.shutdown()
                self._server.server_close()
            if self._server_thread is not None:
                self._server_thread.join(timeout=3)
            if self._worker_thread is not None:
                self._worker_thread.join(timeout=3)
            self._server = None
            self._server_thread = None
            self._worker_thread = None

    def shutdown(self) -> None:
        self.stop()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self._write_config()
        if self._enabled:
            self.start()
        else:
            self.stop()

    def rotate_token(self) -> str:
        self._token = secrets.token_urlsafe(32)
        self._write_config()
        return self._token

    def connection_prompt(self) -> str:
        endpoint = self.endpoint or "http://127.0.0.1:PORT"
        docker_endpoint = (
            self.docker_endpoint or "http://host.docker.internal:PORT")
        return f"""Bạn là agent điều khiển DubFlow qua HTTP local.

Kết nối:
- URL máy này: {endpoint}
- URL khi OpenClaw chạy trong Docker: {docker_endpoint}
- Authorization: Bearer {self.token}
- Chỉ gọi API khi người dùng yêu cầu xử lý video.

Quy trình:
1. Gọi GET /health để kiểm tra DubFlow.
2. Gọi POST /v1/prepare với link video để lấy link hợp lệ và câu hỏi còn thiếu.
3. Hỏi người dùng các lựa chọn còn thiếu như giọng đọc, phong cách dịch và kiểu phụ đề.
4. Gọi POST /v1/submit để tạo batch xử lý.
5. Theo dõi GET /v1/batches/{{batch_id}} và báo tiến trình theo từng video.
6. Khi người dùng yêu cầu dừng, gọi POST /v1/batches/{{batch_id}}/cancel.
7. Khi job lỗi, báo lỗi và chỉ gọi POST /v1/batches/{{batch_id}}/retry-failed khi người dùng xác nhận.
8. Không tự thay đổi tùy chọn người dùng chưa xác nhận.

Endpoint:
- GET /health
- POST /v1/prepare
- POST /v1/submit
- GET /v1/batches/{{batch_id}}
- POST /v1/batches/{{batch_id}}/cancel
- POST /v1/batches/{{batch_id}}/retry-failed

Sau khi gọi /health thành công, báo người dùng rằng DubFlow đã sẵn sàng."""

    def check_health(self) -> tuple[bool, str]:
        if not self.running or not self.endpoint:
            return False, "DubFlow API đang tắt."
        request = Request(
            self.endpoint + "/health",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        try:
            with urlopen(request, timeout=3) as response:
                if response.status == 200:
                    return True, "DubFlow API phản hồi /health."
                return False, f"DubFlow trả về HTTP {response.status}."
        except HTTPError as exc:
            return False, f"DubFlow từ chối kết nối (HTTP {exc.code})."
        except (OSError, URLError) as exc:
            return False, f"Không gọi được DubFlow: {exc}"

    def handle(self, payload: dict) -> dict:
        from autodub.openclaw_tool import handle

        return handle(
            payload,
            queue_root=str(self._queue_root),
            settings=self._settings_provider(),
        )

    def list_batches(self) -> list[dict]:
        batches = []
        directory = self._queue_root / "batches"
        for path in sorted(directory.glob("batch-*.json"),
                           key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                batch_id = str(payload["batch_id"])
                batches.append(self.handle({
                    "action": "status", "batch_id": batch_id}))
            except (OSError, KeyError, TypeError, ValueError,
                    json.JSONDecodeError):
                continue
        return batches
