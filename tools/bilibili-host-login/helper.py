#!/usr/bin/env python3
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


SERVER_ADDRESS = ("127.0.0.1", 18794)
LOGIN_URL = "https://passport.bilibili.com/login"
ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[1]
EXTENSION_DIR = ROOT / "extension"
PROFILE_DIR = Path.home() / ".auto-vietsub" / "bilibili-browser"
OLLAMA_MODEL = "qwen2.5:3b"
ALLOWED_ORIGINS = {
    "http://127.0.0.1:18793",
    "http://localhost:18793",
}


def origin_allowed(origin: str) -> bool:
    return str(origin or "") in ALLOWED_ORIGINS


def chrome_candidates() -> list[Path]:
    paths = []
    for name in ("chrome", "google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        executable = shutil.which(name)
        if executable:
            paths.append(Path(executable))
    if os.name == "nt":
        for root in (
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        ):
            if root:
                paths.extend(
                    (
                        Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe",
                        Path(root) / "Chromium" / "Application" / "chrome.exe",
                        Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                    )
                )
    return paths


def find_chrome() -> Path | None:
    return next((path for path in chrome_candidates() if path.is_file()), None)


def build_chrome_command(chrome: Path) -> list[str]:
    return [
        str(chrome),
        f"--user-data-dir={PROFILE_DIR}",
        f"--disable-extensions-except={EXTENSION_DIR}",
        f"--load-extension={EXTENSION_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        LOGIN_URL,
    ]


def open_login() -> dict:
    chrome = find_chrome()
    if chrome is None:
        return {
            "ok": False,
            "error_code": "ChromeNotFound",
            "message": "Không tìm thấy Chrome, Edge hoặc Chromium.",
        }
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        build_chrome_command(chrome),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=os.name != "nt",
    )
    return {"ok": True, "state": "browser_opened", "pid": process.pid}


def install_ollama(run=subprocess.run, docker=None) -> dict:
    docker = docker or shutil.which("docker")
    if not docker:
        return {"ok": False, "error_code": "DockerNotFound"}
    commands = (
        [docker, "compose", "--profile", "ollama", "up", "-d", "ollama"],
        [
            docker,
            "compose",
            "exec",
            "-T",
            "ollama",
            "ollama",
            "pull",
            OLLAMA_MODEL,
        ],
    )
    errors = ("OllamaServiceStartFailed", "OllamaModelPullFailed")
    for command, error_code in zip(commands, errors):
        try:
            result = run(
                command,
                cwd=REPO_ROOT,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=1800,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error_code": "OllamaInstallTimeout"}
        except OSError:
            return {"ok": False, "error_code": "DockerUnavailable"}
        if result.returncode != 0:
            return {"ok": False, "error_code": error_code}
    return {"ok": True, "state": "ollama_ready", "model": OLLAMA_MODEL}


class Handler(BaseHTTPRequestHandler):
    server_version = "AutoVietsubHostLogin/1"

    def log_message(self, _format, *_args):
        return

    def _origin(self, required=False) -> str:
        origin = self.headers.get("Origin", "")
        if required and not origin_allowed(origin):
            raise PermissionError("unsupported origin")
        if origin and not origin_allowed(origin):
            raise PermissionError("unsupported origin")
        return origin

    def _json(self, status: int, payload: dict, origin: str = "") -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        try:
            origin = self._origin(required=True)
        except PermissionError:
            self._json(403, {"ok": False, "error_code": "OriginRejected"})
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Vary", "Origin")
        self.end_headers()

    def do_GET(self):
        try:
            origin = self._origin()
        except PermissionError:
            self._json(403, {"ok": False, "error_code": "OriginRejected"})
            return
        if self.path != "/status":
            self._json(404, {"ok": False, "error_code": "NotFound"}, origin)
            return
        self._json(
            200,
            {"ok": True, "chrome_available": find_chrome() is not None},
            origin,
        )

    def do_POST(self):
        try:
            origin = self._origin(required=True)
        except PermissionError:
            self._json(403, {"ok": False, "error_code": "OriginRejected"})
            return
        if self.path == "/open":
            result = open_login()
        elif self.path == "/ollama/install":
            result = install_ollama()
        else:
            self._json(404, {"ok": False, "error_code": "NotFound"}, origin)
            return
        self._json(200 if result["ok"] else 503, result, origin)


def main() -> None:
    if not EXTENSION_DIR.is_dir():
        raise SystemExit("Bilibili extension directory is missing")
    server = ThreadingHTTPServer(SERVER_ADDRESS, Handler)
    print("Bilibili host helper: http://127.0.0.1:18794", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
