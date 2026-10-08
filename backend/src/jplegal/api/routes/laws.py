from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select

from jplegal.db.models import LawRecord, LegalRef

router = APIRouter(tags=["laws"])


def _law(r: LawRecord) -> dict:
    return {"law_id": r.law_id, "title": r.title, "abbrev": r.abbrev, "law_num": r.law_num, "law_type": r.law_type,
            "category": r.category, "revision_id": r.revision_id, "source": r.source,
            "enforcement_date": r.enforcement_date, "num_articles": r.num_articles, "num_chunks": r.num_chunks,
            "updated_at": r.updated_at}


@router.get("/laws")
async def list_laws(request: Request, q: str | None = None) -> list[dict]:
    c = request.app.state.c
    async with c.db.session() as s:
        stmt = select(LawRecord).order_by(LawRecord.title)
        if q:
            stmt = stmt.where(LawRecord.title.contains(q))
        return [_law(r) for r in (await s.execute(stmt)).scalars()]


@router.get("/laws/{law_id}")
async def get_law(request: Request, law_id: str) -> dict:
    c = request.app.state.c
    async with c.db.session() as s:
        r = await s.get(LawRecord, law_id)
        if not r:
            raise HTTPException(404, "law not found")
        unresolved = (await s.execute(
            select(LegalRef.target_law_name, func.count()).where(LegalRef.src_law_id == law_id,
                                                                 LegalRef.resolved.is_(False))
            .group_by(LegalRef.target_law_name).order_by(func.count().desc()).limit(30)
        )).all()
    articles = await c.neo4j.law_articles(law_id)
    return {**_law(r), "aliases": r.aliases, "articles": articles,
            "unresolved_targets": [{"name": n, "count": k} for n, k in unresolved]}


@router.get("/articles/graph")
async def article_graph(request: Request, uid: list[str] = Query(...)) -> dict:
    c = request.app.state.c
    details = await c.neo4j.get_articles(uid)
    if not details:
        raise HTTPException(404, "article not found")
    return {"articles": list(details.values()), "graph": await c.neo4j.subgraph(uid)}


@router.get("/graph/stats")
async def graph_stats(request: Request) -> dict:
    c = request.app.state.c
    return {"neo4j": await c.neo4j.stats(), "qdrant_points": await c.qdrant.count()}
