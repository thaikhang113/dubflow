import os
from pathlib import Path
import signal
import subprocess
import threading
import time

from .config import Settings
from .pipeline import build_job_command, build_job_environment, read_job_status
from .secrets import SecretStore, sanitize
from .store import Store

EXIT_ERRORS = {
    20: (
        "BilibiliLoginRequired",
        "Cookie Bilibili bị thiếu, hết hạn hoặc đang yêu cầu xác minh.",
    ),
    21: (
        "BilibiliDownloadFailed",
        "Tải video Bilibili thất bại.",
    ),
}


class Worker:
    def __init__(
        self,
        store: Store,
        settings: Settings,
        secrets: SecretStore,
        cancel_grace: float = 5,
        poll_seconds: float = 1,
        on_update=None,
    ):
        self.store = store
        self.settings = settings
        self.secrets = secrets
        self.cancel_grace = max(0.1, float(cancel_grace))
        self.poll_seconds = max(0.1, float(poll_seconds))
        self.on_update = on_update
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._active_changed = threading.Condition(self._lock)
        self._active = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="video-worker", daemon=True)
        self._thread.start()
        self.notify()

    def notify(self) -> None:
        self._wake.set()

    def set_poll_seconds(self, value: float) -> None:
        self.poll_seconds = max(0.1, float(value))
        self.notify()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        with self._active_changed:
            active = self._active
        if active and active[1]:
            self._terminate(active[1])
        if self._thread:
            self._thread.join(self.cancel_grace + 5)

    def cancel(self, job_id: str) -> bool:
        with self._active_changed:
            if not self._active:
                self._active_changed.wait(timeout=self.cancel_grace)
            active = self._active
            if not active or active[0] != job_id:
                return False
            self._update(
                job_id,
                state="cancelled",
                action="",
                message="Cancelled by user.",
                pid=None,
            )
            process = active[1]
        if process:
            self._terminate(process)
        return True

    def _loop(self) -> None:
        while not self._stop.is_set():
            job = self.store.claim_next_job()
            if job is None:
                self._wake.wait(self.poll_seconds)
                self._wake.clear()
                continue
            if self._stop.is_set():
                return
            with self._active_changed:
                self._active = (job["id"], None)
                self._active_changed.notify_all()
            self._execute(job)

    def _providers(self, job: dict) -> dict:
        request = job.get("request") or {}
        result = {}
        for role, key in (
            ("translation", "translation_provider_id"),
            ("tts", "tts_provider_id"),
        ):
            provider_id = str(request.get(key) or "").strip()
            if not provider_id:
                continue
            provider = self.store.get_provider(provider_id)
            if provider is None:
                raise ValueError(f"{role} provider not found")
            provider = dict(provider)
            provider["api_key"] = self.secrets.environment(provider_id).get(
                "PROVIDER_API_KEY",
                "",
            )
            result[role] = provider
        provider_id = str(request.get("provider_id") or "").strip()
        if provider_id and not result:
            provider = self.store.get_provider(provider_id)
            if provider is None:
                raise ValueError("provider not found")
            provider = dict(provider)
            provider["api_key"] = self.secrets.environment(provider_id).get(
                "PROVIDER_API_KEY",
                "",
            )
            result["tts" if provider["kind"] == "ai33" else "translation"] = provider
        return result

    def _execute(self, job: dict) -> None:
        job_root = self.settings.jobs_dir / job["id"]
        job_root.mkdir(parents=True, exist_ok=True)
        log_path = job_root / "log.txt"
        try:
            command = build_job_command(job, self.settings)
            environment = build_job_environment(
                job,
                self._providers(job),
                self.settings,
            )
        except ValueError as exc:
            self._update(
                job["id"],
                state="failed",
                error_code="JobConfigurationInvalid",
                message=sanitize(exc),
                job_dir=str(job_root),
            )
            self._clear_active(job["id"])
            return

        process_environment = os.environ.copy()
        process_environment.update(environment)
        popen_options = {
            "cwd": self.settings.repo_root,
            "env": process_environment,
            "stdout": None,
            "stderr": subprocess.STDOUT,
            "text": False,
        }
        if os.name == "nt":
            popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_options["start_new_session"] = True

        with log_path.open("ab", buffering=0) as log:
            popen_options["stdout"] = log
            with self._active_changed:
                current = self.store.get_job(job["id"])
                if self._stop.is_set() or current["state"] == "cancelled":
                    self._active = None
                    self._active_changed.notify_all()
                    return
                try:
                    process = subprocess.Popen(command, **popen_options)
                except OSError as exc:
                    self._active = None
                    self._active_changed.notify_all()
                    self._update(
                        job["id"],
                        state="failed",
                        error_code="WorkerStartFailed",
                        message=sanitize(exc),
                        job_dir=str(job_root),
                    )
                    return
                self._active = (job["id"], process)
                self._active_changed.notify_all()
            self._update(
                job["id"],
                job_dir=str(job_root),
                pid=process.pid,
                message="Pipeline running.",
            )
            while process.poll() is None:
                if self._stop.wait(0.25):
                    self._terminate(process)
                    break
                self._refresh(job["id"], job_root)
            return_code = process.wait()

        self._clear_active(job["id"])
        if self._stop.is_set():
            return
        current = self.store.get_job(job["id"])
        if current["state"] == "cancelled":
            return

        output_dir = self._output_dir(job_root)
        status = read_job_status(output_dir or job_root)
        if return_code == 0 and output_dir and self._valid_video(
            output_dir / "final_video_vi.mp4"
        ):
            self._update(
                job["id"],
                state="completed",
                action="",
                job_dir=str(output_dir),
                pid=None,
                error_code="",
                message="Completed.",
                progress=100,
            )
            return

        error_code = str(status.get("error_code") or "")
        message = (
            status.get("error_message")
            or status.get("reason")
            or status.get("label")
            or f"Pipeline exited with code {return_code}."
        )
        if return_code == 0:
            error_code = "FinalVideoInvalid"
            message = "Pipeline did not produce a decodable final_video_vi.mp4."
        elif not error_code and return_code in EXIT_ERRORS:
            error_code, message = EXIT_ERRORS[return_code]
        needs_attention = bool(
            status.get("retry_action")
            or status.get("resume_from_cue")
            or error_code
            or return_code in {7, 8, 20, 21}
        )
        self._update(
            job["id"],
            state="needs_attention" if needs_attention else "failed",
            action="resume" if needs_attention else "",
            job_dir=str(output_dir or job_root),
            pid=None,
            error_code=error_code or "PipelineFailed",
            message=sanitize(message),
            progress=max(current["progress"], self._progress(status)),
        )

    def _refresh(self, job_id: str, job_root: Path) -> None:
        output_dir = self._output_dir(job_root)
        status = read_job_status(output_dir or job_root)
        if not status:
            return
        current = self.store.get_job(job_id)
        fields = {"progress": max(current["progress"], self._progress(status))}
        if output_dir:
            fields["job_dir"] = str(output_dir)
        message = status.get("label") or status.get("error_message") or status.get("reason")
        if message:
            fields["message"] = sanitize(message)
        error_code = status.get("error_code")
        if error_code:
            fields["error_code"] = str(error_code)[:200]
        self._update(job_id, **fields)

    def _update(self, job_id: str, **fields) -> dict:
        job = self.store.update_job(job_id, **fields)
        if self.on_update:
            self.on_update(job)
        return job

    def _clear_active(self, job_id: str) -> None:
        with self._active_changed:
            if self._active and self._active[0] == job_id:
                self._active = None
                self._active_changed.notify_all()

    @staticmethod
    def _progress(status: dict) -> int:
        value = status.get("progress_percent", status.get("progress", 0))
        try:
            return max(0, min(100, int(float(value))))
        except (TypeError, ValueError):
            return 0

    def _output_dir(self, job_root: Path) -> Path | None:
        root = job_root.resolve()
        for pointer in (
            job_root / "LATEST_OUTPUT_DIR.txt",
            job_root / "Bilibili" / "LATEST_OUTPUT_DIR.txt",
        ):
            try:
                candidate = Path(pointer.read_text(encoding="utf-8").splitlines()[0]).resolve()
            except (OSError, IndexError):
                continue
            try:
                candidate.relative_to(root)
            except ValueError:
                continue
            if candidate.is_dir():
                return candidate
        try:
            statuses = sorted(
                job_root.rglob("job_status.json"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return None
        for status in statuses:
            candidate = status.parent.resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                continue
            return candidate
        return None

    @staticmethod
    def _valid_video(path: Path) -> bool:
        if not path.is_file() or path.stat().st_size == 0:
            return False
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=codec_type",
                    "-of",
                    "default=nk=1:nw=1",
                    str(path),
                ],
                capture_output=True,
                check=False,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0 and "video" in result.stdout

    def _terminate(self, process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "nt":
                process.terminate()
            else:
                os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=self.cancel_grace)
        except (OSError, subprocess.TimeoutExpired):
            try:
                if os.name == "nt":
                    process.kill()
                else:
                    os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass
            try:
                process.wait(timeout=self.cancel_grace)
            except subprocess.TimeoutExpired:
                pass
