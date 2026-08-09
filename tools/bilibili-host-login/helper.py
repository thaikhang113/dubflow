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
HARDWARE_STATE_PATH = Path.home() / ".auto-vietsub" / "hardware.json"
OLLAMA_MODEL = "translategemma:4b"
WHISPER_MODELS = {"small", "medium"}
HARDWARE_MODES = {"auto", "cpu", "gpu"}
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

def install_whisper(model: str, run=subprocess.run, docker=None) -> dict:
    model = str(model or "").strip().lower()
    if model not in WHISPER_MODELS:
        return {"ok": False, "error_code": "WhisperModelInvalid"}
    docker = docker or shutil.which("docker")
    if not docker:
        return {"ok": False, "error_code": "DockerNotFound"}
    try:
        result = run(
            [
                docker,
                "compose",
                "exec",
                "-T",
                "tool",
                "bash",
                "/opt/whisper.cpp/models/download-ggml-model.sh",
                model,
                "/data/models/whisper.cpp/models",
            ],
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=1800,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error_code": "WhisperInstallTimeout"}
    except OSError:
        return {"ok": False, "error_code": "DockerUnavailable"}
    if result.returncode != 0:
        return {"ok": False, "error_code": "WhisperModelPullFailed"}
    return {"ok": True, "state": "whisper_ready", "model": model}

def detect_hardware(run=subprocess.run, docker=None) -> dict:
    docker = docker or shutil.which("docker")
    try:
        gpu = run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        gpu = None
    rows = []
    if gpu and gpu.returncode == 0:
        for line in str(gpu.stdout or "").splitlines():
            try:
                name, memory = line.rsplit(",", 1)
                rows.append((name.strip(), int(memory.strip())))
            except (TypeError, ValueError):
                continue
    stages = {"ollama": "cpu", "whisper": "cpu", "demucs": "cpu", "render": "cpu"}
    if not rows:
        return {
            "ok": True,
            "gpu": None,
            "docker_gpu": False,
            "recommended_profile": "cpu",
            "fallback_reason": "GpuNotFound",
            "stages": stages,
        }
    name, memory_mb = max(rows, key=lambda item: item[1])
    docker_gpu = False
    if docker:
        try:
            smoke = run(
                [
                    docker, "run", "--rm", "--gpus", "all",
                    "--entrypoint", "nvidia-smi",
                    "ollama/ollama:latest",
                    "--query-gpu=name",
                    "--format=csv,noheader",
                ],
                cwd=REPO_ROOT,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=120,
                check=False,
            )
            docker_gpu = smoke.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            pass
    if docker_gpu:
        stages["ollama"] = "gpu"
    return {
        "ok": True,
        "gpu": {"name": name, "memory_mb": memory_mb},
        "docker_gpu": docker_gpu,
        "recommended_profile": (
            "gpu" if memory_mb >= 6144 else "hybrid"
        ) if docker_gpu else "cpu",
        "fallback_reason": "" if docker_gpu else "DockerGpuUnavailable",
        "stages": stages,
    }

def apply_hardware_mode(
    mode: str,
    run=subprocess.run,
    docker=None,
    state_path: Path = HARDWARE_STATE_PATH,
) -> dict:
    mode = str(mode or "").strip().lower()
    if mode not in HARDWARE_MODES:
        return {"ok": False, "error_code": "HardwareModeInvalid"}
    docker = docker or shutil.which("docker")
    detection = detect_hardware(run=run, docker=docker)
    selected = (
        detection["recommended_profile"]
        if mode != "cpu" and detection["docker_gpu"]
        else "cpu"
    )
    if not docker:
        return {**detection, "ok": False, "error_code": "DockerNotFound"}
    command = [
        docker, "compose", "--profile", "ollama",
        "up", "-d", "--force-recreate", "ollama",
    ] if selected == "cpu" else [
        docker, "compose",
        "-f", "compose.yaml",
        "-f", "compose.gpu.yaml",
        "--profile", "ollama",
        "up", "-d", "--force-recreate", "ollama",
    ]
    try:
        result = run(
            command,
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {**detection, "ok": False, "error_code": "DockerUnavailable"}
    if result.returncode != 0:
        return {**detection, "ok": False, "error_code": "HardwareApplyFailed"}
    payload = {
        **detection,
        "ok": True,
        "requested_mode": mode,
        "selected_profile": selected,
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload

def read_hardware_state(path: Path = HARDWARE_STATE_PATH) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def hardware_status(detection: dict, saved: dict) -> dict:
    return {
        **detection,
        "requested_mode": saved.get("requested_mode", "auto"),
        "selected_profile": saved.get(
            "selected_profile",
            detection.get("recommended_profile", "cpu"),
        ),
    }


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
        if self.path == "/hardware":
            self._json(
                200,
                hardware_status(detect_hardware(), read_hardware_state()),
                origin,
            )
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
        elif self.path == "/whisper/install":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 1024:
                    raise ValueError
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError
            except (ValueError, UnicodeError, json.JSONDecodeError):
                self._json(400, {"ok": False, "error_code": "InvalidJson"}, origin)
                return
            result = install_whisper(payload.get("model"))
        elif self.path == "/hardware/apply":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 1024:
                    raise ValueError
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError
            except (ValueError, UnicodeError, json.JSONDecodeError):
                self._json(400, {"ok": False, "error_code": "InvalidJson"}, origin)
                return
            result = apply_hardware_mode(payload.get("mode"))
        else:
            self._json(404, {"ok": False, "error_code": "NotFound"}, origin)
            return
        self._json(200 if result["ok"] else 503, result, origin)


def main() -> None:
    if not EXTENSION_DIR.is_dir():
        raise SystemExit("Bilibili extension directory is missing")
    apply_hardware_mode(read_hardware_state().get("requested_mode", "auto"))
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
