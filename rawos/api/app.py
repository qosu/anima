"""rawos FastAPI application — entry point."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import rawos.db as db
from rawos.config import settings
from rawos.api.auth_routes  import router as auth_router
from rawos.api.project_routes import router as project_router
from rawos.api.intent_routes  import router as intent_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init(settings.db_path)
    Path(settings.workspaces_root).mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="rawos",
    version="0.1.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router,    prefix="/auth",     tags=["auth"])
app.include_router(project_router, prefix="/projects", tags=["projects"])
app.include_router(intent_router,  prefix="/intent",   tags=["intent"])


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}
