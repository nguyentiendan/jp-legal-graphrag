"""FastAPI app. Mọi route nằm dưới /api (Nginx proxy /api → service api:8000)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from jplegal.api.routes import ask, ingest, jobs, laws, system
from jplegal.core.config import get_settings
from jplegal.core.container import Container
from jplegal.worker.jobs import get_pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    app.state.c = await Container.create(s)
    app.state.pool = await get_pool(s.redis_url)
    yield
    await app.state.pool.aclose()
    await app.state.c.close()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="JP Legal GraphRAG API", version="0.1.0", lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json")
    if s.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in s.cors_origins.split(",")],
                           allow_methods=["*"], allow_headers=["*"])
    for r in (system.router, ingest.router, jobs.router, laws.router, ask.router):
        app.include_router(r, prefix="/api")
    return app


app = create_app()
