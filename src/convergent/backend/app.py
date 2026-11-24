"""FastAPI application factory.

Startup applies Alembic migrations (``run_migrations``) so the schema is always at ``head``;
errors are returned as a consistent ``{"error", "detail", "code"}`` JSON body.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from convergent.backend.database import Database, run_migrations
from convergent.backend.routes.api_v1 import API_VERSION
from convergent.backend.routes.api_v1 import router as api_router
from convergent.backend.routes.app_v1 import router as app_router
from convergent.backend.routes.ws_v1 import router as ws_router
from convergent.backend.ws import Hub, jsonable
from convergent.common.config import Settings, load_settings
from convergent.common.logging import configure_logging, get_logger

log = get_logger(__name__)


def create_app(settings: Settings | None = None, database_url: str | None = None, migrate: bool = True) -> FastAPI:
    settings = settings or load_settings()
    url = database_url or settings.database_url

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        configure_logging(settings.log_level, settings.log_dir, "backend", settings.log_max_bytes, settings.log_backup_count)
        app.state.migration_revision = run_migrations(url) if migrate else None
        app.state.db = Database(url, settings)
        app.state.hub = Hub()
        app.state.started_monotonic = time.monotonic()
        if not settings.api_token:
            log.warning("CONVERGENT_API_TOKEN is empty: write endpoints are disabled (fail closed)")
        yield
        app.state.db.dispose()

    app = FastAPI(title="Convergent Handwashing Backend", version=API_VERSION, lifespan=lifespan)
    app.state.settings = settings
    app.include_router(api_router)
    app.include_router(app_router)
    app.include_router(ws_router)
    _serve_web(app)

    @app.exception_handler(StarletteHTTPException)
    async def _http_exc(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail), "detail": None, "code": f"http_{exc.status_code}"},
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_exc(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": "validation error", "detail": jsonable(exc.errors()), "code": "validation_error"})

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error: %s", exc)
        return JSONResponse(status_code=500, content={"error": "internal server error", "detail": None, "code": "internal_error"})

    return app


WEB_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"


def _serve_web(app: FastAPI) -> None:
    """Serve the built parent app (web/dist) at /. Unknown paths get index.html so app links survive a reload."""
    if not (WEB_DIST / "index.html").exists():
        return
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="web-assets")

    @app.get("/{path:path}", include_in_schema=False)
    def _web(path: str) -> FileResponse:
        f = (WEB_DIST / path).resolve()
        if path and f.is_file() and WEB_DIST in f.parents:
            return FileResponse(f)
        if path.startswith(("api/", "ws/", "health", "docs", "openapi")):
            raise StarletteHTTPException(404)
        return FileResponse(WEB_DIST / "index.html")


def run(host: str | None = None, port: int | None = None, reload: bool = False) -> None:
    import uvicorn

    settings = load_settings()
    uvicorn.run("convergent.backend.app:create_app", factory=True, host=host or settings.api_host, port=port or settings.api_port,
                reload=reload, log_level=settings.log_level.lower())
