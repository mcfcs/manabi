from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from manabi_server.api import courses, documents, health, jobs, modules, notes, user
from manabi_server.config import get_settings

app = FastAPI(title="Manabi", docs_url="/api/docs", openapi_url="/api/openapi.json")

app.include_router(health.router)
app.include_router(user.router)
app.include_router(jobs.router)
app.include_router(courses.router)
app.include_router(modules.router)
app.include_router(documents.router)
app.include_router(notes.router)

# Serve the built SPA (apps/web/dist) so one process on 0.0.0.0:56690 covers
# API + website for every device on the tailnet. During `pnpm dev`, Vite
# serves the SPA itself and proxies /api here instead.
_web_dist = Path(get_settings().web_dist).resolve()

if (_web_dist / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=_web_dist / "assets"), name="assets")

if (_web_dist / "index.html").is_file():

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = (_web_dist / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(_web_dist):
            return FileResponse(candidate)
        return FileResponse(_web_dist / "index.html")
