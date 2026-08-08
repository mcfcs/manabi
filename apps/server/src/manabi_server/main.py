from fastapi import FastAPI

from manabi_server.api import auth, health, jobs

app = FastAPI(title="Manabi", docs_url="/api/docs", openapi_url="/api/openapi.json")

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(jobs.router)
