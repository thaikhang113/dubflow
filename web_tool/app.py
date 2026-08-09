import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import re
import tempfile
import threading
import uuid
import zipfile

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from .bilibili_login import BilibiliLogin
from .config import Settings
from .integrations import (
    hyperframes_status,
    run_series_action,
    run_trend_action,
    host_login_helper_available,
    runtime_doctor,
    test_telegram,
    thumbnail_status,
)
from .monitor import MonitorScheduler
from .pipeline import build_job_command, build_job_environment
from .secrets import SecretStore, sanitize, test_provider_connection, validate_provider
from .store import Store
from .worker import Worker

ARTIFACTS = {
    "final_video_vi.mp4",
    "vietnamese.srt",
    "dub.srt",
    "thumbnail.jpg",
    "voice_sync_quality_report.json",
    "final_mix_quality_report.json",
    "bilibili_branding_proof.json",
}
UPLOAD_EXTENSIONS = {".avi", ".mkv", ".mov", ".mp4", ".webm"}
UPLOAD_MAX_BYTES = 20 * 1024 * 1024 * 1024


class EventBroker:
    def __init__(self):
        self._subscribers = set()
        self._lock = threading.Lock()

    def subscribe(self, loop) -> asyncio.Queue:
        queue = asyncio.Queue(maxsize=100)
        with self._lock:
            self._subscribers.add((loop, queue))
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers = {
                subscriber
                for subscriber in self._subscribers
                if subscriber[1] is not queue
            }

    def publish(self, job: dict) -> None:
        payload = _public_job(job)
        stale = []
        with self._lock:
            subscribers = tuple(self._subscribers)
        for loop, queue in subscribers:
            def deliver(target=queue, value=payload):
                if target.full():
                    target.get_nowait()
                target.put_nowait(value)

            try:
                loop.call_soon_threadsafe(deliver)
            except RuntimeError:
                stale.append(queue)
        for queue in stale:
            self.unsubscribe(queue)


class ProviderRequest(BaseModel):
    name: str
    kind: str
    endpoint: str
    model: str = ""
    timeout_seconds: int = Field(default=90, ge=1, le=600)
    api_key: str = ""


class JobRequest(BaseModel):
    platform: str
    source: str
    translation_provider_id: str = ""
    tts_provider_id: str = ""
    provider_id: str = ""
    model: str = ""
    voice: str = ""
    series_id: str = ""
    preset: str = ""


class CookieImportRequest(BaseModel):
    text: str

class ChannelRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    platform: str
    url: str
    interval_minutes: int = Field(default=60, ge=1, le=10080)
    enabled: bool = True
    provider_id: str = ""
    model: str = Field(default="", max_length=200)
    voice: str = Field(default="", max_length=200)
    series_id: str = Field(default="", max_length=200)
    preset: dict = Field(default_factory=dict)

class IntegrationRequest(BaseModel):
    payload: dict = Field(default_factory=dict)

class RuntimeSettingsRequest(BaseModel):
    default_provider_id: str = ""
    default_model: str = Field(default="qwen2.5:3b", max_length=200)
    default_voice: str = Field(
        default="ai33:vbee_hn_female_ngochuyen_full_48k-fhg",
        max_length=200,
    )
    queue_poll_seconds: int = Field(default=2, ge=1, le=60)
    telegram_chat_id: str = Field(default="", max_length=100)
    telegram_thread_id: str = Field(default="", max_length=100)
    telegram_bot_token: str = Field(default="", max_length=500)


def _public_value(value):
    if isinstance(value, str):
        return sanitize(value)
    if isinstance(value, list):
        return [_public_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _public_value(item) for key, item in value.items()}
    return value


def _public_job(job: dict) -> dict:
    return _public_value(job)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    static_dir = Path(__file__).with_name("static")
    store = Store(settings.database_path)
    secrets = SecretStore(settings.secrets_dir)
    events = EventBroker()
    bilibili_login = BilibiliLogin(settings, secrets)
    initial_runtime = store.get_settings({"queue_poll_seconds": "2"})
    worker = Worker(
        store,
        settings,
        secrets,
        poll_seconds=float(initial_runtime["queue_poll_seconds"]),
        on_update=events.publish,
    )
    monitor = MonitorScheduler(
        store,
        settings,
        on_enqueue=lambda job: (events.publish(job), worker.notify()),
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        store.recover_running_jobs()
        worker.start()
        monitor.start()
        try:
            yield
        finally:
            monitor.stop()
            worker.stop()

    app = FastAPI(title="Auto Vietsub Tool", version="1", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store
    app.state.secrets = secrets
    app.state.worker = worker
    app.state.events = events
    app.state.bilibili_login = bilibili_login
    app.state.monitor = monitor
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": 1}

    @app.get("/api/providers")
    def list_providers():
        return store.list_providers()

    @app.post("/api/providers", status_code=status.HTTP_201_CREATED)
    def create_provider(request: ProviderRequest):
        try:
            values = validate_provider(request.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        provider = store.create_provider(values, has_secret=bool(request.api_key.strip()))
        if request.api_key.strip():
            try:
                secrets.write(provider["id"], request.api_key)
            except Exception:
                store.delete_provider(provider["id"])
                raise
        return provider

    @app.delete("/api/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_provider(provider_id: str):
        if not store.delete_provider(provider_id):
            raise HTTPException(status_code=404, detail="provider not found")
        secrets.delete(provider_id)

    @app.put("/api/providers/{provider_id}")
    def update_provider(provider_id: str, request: ProviderRequest):
        if store.get_provider(provider_id) is None:
            raise HTTPException(status_code=404, detail="provider not found")
        try:
            values = validate_provider(request.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        has_secret = None
        if request.api_key.strip():
            secrets.write(provider_id, request.api_key)
            has_secret = True
        provider = store.update_provider(provider_id, values, has_secret)
        return provider

    @app.post("/api/providers/{provider_id}/test")
    def test_provider(provider_id: str):
        provider = store.get_provider(provider_id)
        if provider is None:
            raise HTTPException(status_code=404, detail="provider not found")
        return test_provider_connection(provider, secrets)

    @app.post("/api/bilibili/login/start")
    def start_bilibili_login():
        return bilibili_login.start()

    @app.get("/api/bilibili/login/qr")
    def bilibili_login_qr():
        try:
            image = bilibili_login.qr_png()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="QR code is not available") from exc
        return Response(image, media_type="image/png")

    @app.get("/api/bilibili/login/status")
    def bilibili_login_status():
        return bilibili_login.status()

    @app.post("/api/bilibili/login/cookies")
    def import_bilibili_cookies(request: CookieImportRequest):
        try:
            return bilibili_login.import_netscape(request.text)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.delete("/api/bilibili/login/cookies")
    def clear_bilibili_login():
        return bilibili_login.clear()

    def validate_channel(request: ChannelRequest) -> dict:
        values = request.model_dump()
        values["platform"] = values["platform"].strip().lower()
        values["url"] = values["url"].strip()
        values["name"] = values["name"].strip()
        values["provider_id"] = values["provider_id"].strip()
        try:
            build_job_command(
                {"platform": values["platform"], "source": values["url"]},
                settings,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if values["provider_id"] and store.get_provider(values["provider_id"]) is None:
            raise HTTPException(status_code=422, detail="provider_id not found")
        return values

    @app.get("/api/channels")
    def list_channels():
        return store.list_channels()

    @app.post("/api/channels", status_code=status.HTTP_201_CREATED)
    def create_channel(request: ChannelRequest):
        channel = store.create_channel(validate_channel(request))
        monitor.notify()
        return channel

    @app.put("/api/channels/{channel_id}")
    def update_channel(channel_id: str, request: ChannelRequest):
        channel = store.update_channel(channel_id, validate_channel(request))
        if channel is None:
            raise HTTPException(status_code=404, detail="channel not found")
        monitor.notify()
        return channel

    @app.delete("/api/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_channel(channel_id: str):
        if not store.delete_channel(channel_id):
            raise HTTPException(status_code=404, detail="channel not found")

    @app.post("/api/channels/{channel_id}/run")
    def run_channel(channel_id: str):
        channel = store.schedule_channel_now(channel_id)
        if channel is None:
            raise HTTPException(status_code=409, detail="channel not found or disabled")
        monitor.notify()
        return channel

    @app.post("/api/channels/{channel_id}/enable")
    def enable_channel(channel_id: str):
        channel = store.set_channel_enabled(channel_id, True)
        if channel is None:
            raise HTTPException(status_code=404, detail="channel not found")
        monitor.notify()
        return channel

    @app.post("/api/channels/{channel_id}/disable")
    def disable_channel(channel_id: str):
        channel = store.set_channel_enabled(channel_id, False)
        if channel is None:
            raise HTTPException(status_code=404, detail="channel not found")
        return channel

    def integration_call(function, action, payload):
        try:
            return function(action, payload, settings)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/series/list")
    def series_list():
        return integration_call(run_series_action, "list", {})

    @app.post("/api/series/{action}")
    def series_action(action: str, request: IntegrationRequest):
        return integration_call(run_series_action, action, request.payload)

    @app.post("/api/trend/{action}")
    def trend_action(action: str, request: IntegrationRequest):
        return integration_call(run_trend_action, action, request.payload)

    def public_settings():
        values = store.get_settings(
            {
                "default_provider_id": "",
                "default_model": "qwen2.5:3b",
                "default_voice": "ai33:vbee_hn_female_ngochuyen_full_48k-fhg",
                "queue_poll_seconds": "2",
                "telegram_chat_id": "",
                "telegram_thread_id": "",
            }
        )
        values["queue_poll_seconds"] = int(values["queue_poll_seconds"])
        values["telegram_configured"] = secrets.read_status("telegram-bot")["configured"]
        values["ai33_workers"] = 3
        return values

    @app.get("/api/settings")
    def get_runtime_settings():
        return public_settings()

    @app.put("/api/settings")
    def update_runtime_settings(request: RuntimeSettingsRequest):
        values = request.model_dump()
        provider_id = values["default_provider_id"].strip()
        if provider_id and store.get_provider(provider_id) is None:
            raise HTTPException(status_code=422, detail="default_provider_id not found")
        for key, pattern in (
            ("telegram_chat_id", r"-?[0-9]+"),
            ("telegram_thread_id", r"[0-9]+"),
        ):
            value = values[key].strip()
            if value and not re.fullmatch(pattern, value):
                raise HTTPException(status_code=422, detail=f"invalid {key}")
        token = values.pop("telegram_bot_token").strip()
        if token:
            secrets.write("telegram-bot", token)
        store.set_settings(
            {
                key: str(value).strip()
                for key, value in values.items()
            }
        )
        worker.set_poll_seconds(values["queue_poll_seconds"])
        return public_settings()

    @app.get("/api/runtime/doctor")
    def doctor():
        values = public_settings()
        return runtime_doctor(
            settings,
            store.list_providers(),
            runtime_settings=values,
            login_status=bilibili_login.status(),
            telegram_configured=values["telegram_configured"],
            host_helper_available=host_login_helper_available(),
        )

    @app.post("/api/telegram/test")
    def telegram_test():
        values = public_settings()
        return test_telegram(
            secrets,
            values["telegram_chat_id"],
            values["telegram_thread_id"],
        )

    @app.get("/api/hyperframes/status")
    def get_hyperframes_status():
        try:
            return hyperframes_status(settings)
        except ValueError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/thumbnail/status")
    def get_thumbnail_status():
        return thumbnail_status(settings)

    @app.get("/api/runtime/export")
    def export_output():
        temporary = tempfile.NamedTemporaryFile(
            prefix="auto-vietsub-output-",
            suffix=".zip",
            dir=settings.data_dir,
            delete=False,
        )
        temporary.close()
        archive_path = Path(temporary.name)
        output_root = settings.output_dir.resolve()
        try:
            with zipfile.ZipFile(
                archive_path,
                "w",
                compression=zipfile.ZIP_DEFLATED,
            ) as archive:
                for path in sorted(settings.output_dir.rglob("*")):
                    if not path.is_file() or path.is_symlink():
                        continue
                    resolved = path.resolve()
                    try:
                        relative = resolved.relative_to(output_root)
                    except ValueError:
                        continue
                    archive.write(resolved, relative.as_posix())
        except Exception:
            archive_path.unlink(missing_ok=True)
            raise
        return FileResponse(
            archive_path,
            filename="auto-vietsub-output.zip",
            background=BackgroundTask(archive_path.unlink, missing_ok=True),
        )

    @app.get("/api/jobs")
    def list_jobs(limit: int = 100):
        return [_public_job(job) for job in store.list_jobs(limit)]

    @app.post("/api/uploads", status_code=status.HTTP_201_CREATED)
    def upload_video(file: UploadFile = File(...)):
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in UPLOAD_EXTENSIONS:
            raise HTTPException(status_code=422, detail="unsupported video file type")
        upload_dir = settings.jobs_dir / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        upload_id = uuid.uuid4().hex
        target = upload_dir / f"{upload_id}{suffix}"
        temporary = upload_dir / f".{upload_id}.tmp"
        total = 0
        try:
            with temporary.open("xb") as output:
                while chunk := file.file.read(1024 * 1024):
                    total += len(chunk)
                    if total > UPLOAD_MAX_BYTES:
                        raise HTTPException(status_code=413, detail="video file is too large")
                    output.write(chunk)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return {"source": str(target.resolve())}

    @app.post("/api/jobs", status_code=status.HTTP_201_CREATED)
    def create_job(request: JobRequest):
        values = request.model_dump()
        defaults = store.get_settings(
            {
                "default_provider_id": "",
                "default_model": "qwen2.5:3b",
                "default_voice": "ai33:vbee_hn_female_ngochuyen_full_48k-fhg",
            }
        )
        if not values["model"].strip():
            values["model"] = defaults["default_model"]
        if not values["voice"].strip():
            values["voice"] = defaults["default_voice"]
        if not any(
            values[key].strip()
            for key in ("translation_provider_id", "tts_provider_id", "provider_id")
        ):
            default_provider_id = defaults["default_provider_id"].strip()
            provider = store.get_provider(default_provider_id) if default_provider_id else None
            if provider:
                role = (
                    "tts_provider_id"
                    if provider["kind"] == "ai33"
                    else "translation_provider_id"
                )
                values[role] = provider["id"]
        if (
            values["voice"].lower().startswith("ai33:")
            and not values["tts_provider_id"].strip()
        ):
            ai33 = [
                provider
                for provider in store.list_providers()
                if provider["kind"] == "ai33" and provider["configured"]
            ]
            if len(ai33) == 1:
                values["tts_provider_id"] = ai33[0]["id"]
        try:
            build_job_command(values, settings)
            providers = {}
            for role, key in (
                ("translation", "translation_provider_id"),
                ("tts", "tts_provider_id"),
            ):
                provider_id = values[key].strip()
                if provider_id:
                    provider = store.get_provider(provider_id)
                    if provider is None:
                        raise ValueError(f"{key} not found")
                    providers[role] = provider
            provider_id = values["provider_id"].strip()
            if provider_id and not providers:
                provider = store.get_provider(provider_id)
                if provider is None:
                    raise ValueError("provider_id not found")
                providers["tts" if provider["kind"] == "ai33" else "translation"] = provider
            build_job_environment(
                {"id": "job-validation", **values},
                providers,
                settings,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        job = store.enqueue_job(values)
        events.publish(job)
        worker.notify()
        return _public_job(job)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return _public_job(job)

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        if worker.cancel(job_id):
            cancelled = store.get_job(job_id)
        else:
            try:
                cancelled = store.cancel_waiting_job(job_id)
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        events.publish(cancelled)
        return _public_job(cancelled)

    @app.post("/api/jobs/{job_id}/resume")
    def resume_job(job_id: str):
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        if not job["job_dir"]:
            raise HTTPException(status_code=409, detail="job has no checkpoint directory")
        request = dict(job["request"])
        request["resume_job_dir"] = str(Path(job["job_dir"]).resolve())
        if not any(
            str(request.get(key) or '').strip()
            for key in ('translation_provider_id', 'tts_provider_id', 'provider_id')
        ):
            default_id = store.get_settings(
                {'default_provider_id': ''}
            )['default_provider_id'].strip()
            provider = store.get_provider(default_id) if default_id else None
            if provider:
                role = (
                    'tts_provider_id'
                    if provider['kind'] == 'ai33'
                    else 'translation_provider_id'
                )
                request[role] = provider['id']
        if (
            str(request.get('voice') or '').lower().startswith('ai33:')
            and not str(request.get('tts_provider_id') or '').strip()
        ):
            ai33 = [
                provider
                for provider in store.list_providers()
                if provider['kind'] == 'ai33' and provider['configured']
            ]
            if len(ai33) == 1:
                request['tts_provider_id'] = ai33[0]['id']
        candidate = dict(job)
        candidate["request"] = request
        try:
            build_job_command(candidate, settings)
            resumed = store.requeue_for_resume(job_id, request)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        events.publish(resumed)
        worker.notify()
        return _public_job(resumed)

    @app.post("/api/jobs/{job_id}/retry", status_code=status.HTTP_201_CREATED)
    def retry_job(job_id: str):
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        request = dict(job["request"])
        request.pop("resume_job_dir", None)
        request["retry_of"] = job_id
        retried = store.enqueue_job(request)
        events.publish(retried)
        worker.notify()
        return _public_job(retried)

    @app.post("/api/queue/pause")
    def pause_queue():
        store.set_queue_paused(True)
        return {"paused": True}

    @app.post("/api/queue/resume")
    def resume_queue():
        store.set_queue_paused(False)
        worker.notify()
        return {"paused": False}

    @app.get("/api/events")
    async def job_events(request: Request):
        loop = asyncio.get_running_loop()
        queue = events.subscribe(loop)

        async def stream():
            try:
                yield ": connected\n\n"
                while not await request.is_disconnected():
                    try:
                        job = await asyncio.wait_for(queue.get(), timeout=15)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                    else:
                        data = json.dumps(job, ensure_ascii=False, separators=(",", ":"))
                        yield f"event: job\ndata: {data}\n\n"
            finally:
                events.unsubscribe(queue)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/api/jobs/{job_id}/artifacts/{name:path}")
    def get_artifact(job_id: str, name: str):
        if name not in ARTIFACTS:
            raise HTTPException(status_code=404, detail="artifact not found")
        job = store.get_job(job_id)
        if job is None or not job["job_dir"]:
            raise HTTPException(status_code=404, detail="artifact not found")
        job_dir = Path(job["job_dir"]).resolve()
        try:
            job_dir.relative_to(settings.jobs_dir.resolve())
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="artifact not found") from exc
        artifact = (job_dir / name).resolve()
        if artifact.parent != job_dir or not artifact.is_file():
            raise HTTPException(status_code=404, detail="artifact not found")
        if artifact.suffix == ".json":
            try:
                payload = json.loads(artifact.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise HTTPException(status_code=404, detail="artifact not found") from exc
            return JSONResponse(
                _public_value(payload),
                headers={"Content-Disposition": f'attachment; filename="{name}"'},
            )
        return FileResponse(artifact, filename=name)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(static_dir / "index.html")

    return app
