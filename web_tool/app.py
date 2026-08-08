from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .store import Store


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    static_dir = Path(__file__).with_name("static")
    store = Store(settings.database_path)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        store.recover_running_jobs()
        yield

    app = FastAPI(title="Auto Vietsub Tool", version="1", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": 1}

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(static_dir / "index.html")

    return app
