from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings
from .secrets import SecretStore, test_provider_connection, validate_provider
from .store import Store


class ProviderRequest(BaseModel):
    name: str
    kind: str
    endpoint: str
    model: str = ""
    timeout_seconds: int = Field(default=90, ge=1, le=600)
    api_key: str = ""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    static_dir = Path(__file__).with_name("static")
    store = Store(settings.database_path)
    secrets = SecretStore(settings.secrets_dir)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        store.recover_running_jobs()
        yield

    app = FastAPI(title="Auto Vietsub Tool", version="1", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store
    app.state.secrets = secrets
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

    @app.post("/api/providers/{provider_id}/test")
    def test_provider(provider_id: str):
        provider = store.get_provider(provider_id)
        if provider is None:
            raise HTTPException(status_code=404, detail="provider not found")
        return test_provider_connection(provider, secrets)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(static_dir / "index.html")

    return app
