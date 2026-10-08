from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/status")
async def status(request: Request) -> dict:
    """Kiểm tra kết nối tới từng service phụ thuộc."""
    c = request.app.state.c

    async def check(name: str, coro):
        try:
            return name, {"ok": True, "info": await asyncio.wait_for(coro, timeout=5)}
        except Exception as e:
            return name, {"ok": False, "error": str(e)[:200]}

    async def pg():
        from sqlalchemy import text

        async with c.db.session() as s:
            return (await s.execute(text("SELECT 1"))).scalar()

    results = await asyncio.gather(
        check("postgres", pg()),
        check("redis", c.redis.ping()),
        check("qdrant", c.qdrant.count()),
        check("neo4j", c.neo4j.stats()),
        check("model_server", c.models.health()),
    )
    out = dict(results)
    out["llm"] = {"ok": c.llm.enabled, "model": c.settings.llm_model or None}
    return out
