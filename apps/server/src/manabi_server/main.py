import asyncio
import contextlib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from manabi_server.api import (
    artifacts,
    calendar,
    canvas,
    chat,
    courses,
    documents,
    health,
    jobs,
    modules,
    notes,
    push,
    review,
    schedule,
    search,
    stats,
    tasks,
    user,
)
from manabi_server.api import (
    settings as settings_api,
)
from manabi_server.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    from manabi_server import db as db_mod
    from manabi_server.services.scheduler import run_scheduler

    db_mod.get_engine()
    task = asyncio.create_task(run_scheduler(db_mod._sessionmaker))
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(
    title="Manabi",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(user.router)
app.include_router(jobs.router)
app.include_router(courses.router)
app.include_router(modules.router)
app.include_router(documents.router)
app.include_router(notes.router)
app.include_router(artifacts.router)
app.include_router(chat.router)
app.include_router(canvas.router)
app.include_router(schedule.router)
app.include_router(calendar.router)
app.include_router(tasks.router)
app.include_router(push.router)
app.include_router(review.router)
app.include_router(search.router)
app.include_router(stats.router)
app.include_router(settings_api.router)

# Serve the built SPA (apps/web/dist) so one process on 0.0.0.0:56690 covers
# API + website for every device on the tailnet. During `pnpm dev`, Vite
# serves the SPA itself and proxies /api here instead.
_web_dist = Path(get_settings().web_dist).resolve()


class _HashedAssets(StaticFiles):
    """Vite assets are content-hashed — cache them forever."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


if (_web_dist / "assets").is_dir():
    app.mount("/assets", _HashedAssets(directory=_web_dist / "assets"), name="assets")

if (_web_dist / "index.html").is_file():

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = (_web_dist / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(_web_dist):
            # top-level files (icons, manifest) may change between builds
            return FileResponse(candidate, headers={"Cache-Control": "no-cache"})
        # index.html must ALWAYS revalidate or users get a stale app shell
        return FileResponse(
            _web_dist / "index.html", headers={"Cache-Control": "no-cache"}
        )
