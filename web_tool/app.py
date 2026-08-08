import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import threading
import uuid

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings
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
    voice: str = ""
    series_id: str = ""
    preset: str = ""


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
    worker = Worker(store, settings, secrets, on_update=events.publish)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        store.recover_running_jobs()
        worker.start()
        try:
            yield
        finally:
            worker.stop()

    app = FastAPI(title="Auto Vietsub Tool", version="1", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store
    app.state.secrets = secrets
    app.state.worker = worker
    app.state.events = events
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
