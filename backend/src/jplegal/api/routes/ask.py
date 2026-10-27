"""/api/search (retrieval only) and /api/ask (retrieval + LLM, SSE stream).

SSE events of /api/ask:
    event: retrieval   data: {items, timings_ms, subgraph}
    event: token       data: {"t": "..."}
    event: done        data: {"answer": "...", "citations": [...], "guard": {"unsupported": [...], "warnings": [...]}}
    event: error       data: {"message": "..."}
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from jplegal.retrieval.answer import build_messages
from jplegal.retrieval.guardrails import guard_answer
from jplegal.retrieval.intent import QueryIntent, classify_intent, direct_answer
from jplegal.retrieval.pipeline import RetrievalOptions, RetrievalResult, RetrievedArticle, Retriever
from jplegal.retrieval.relevance import ArticleRelevance, judge_articles

router = APIRouter(tags=["retrieval"])
log = logging.getLogger(__name__)


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    law_ids: list[str] | None = None
    use_graph: bool = True
    use_rerank: bool = True
    use_sparse: bool | None = None  # None = follow SPARSE_ENABLED
    top_k: int | None = Field(None, ge=1, le=30)


def _opts(b: QueryRequest) -> RetrievalOptions:
    return RetrievalOptions(use_graph=b.use_graph, use_rerank=b.use_rerank, use_sparse=b.use_sparse,
                            law_ids=b.law_ids or None, final_k=b.top_k)


def _jev(c):
    return c.jev if c.jev.enabled else None


def _done(answer: str, items: list[RetrievedArticle], citations: list[dict]) -> str:
    guarded = guard_answer(answer, [it.citation for it in items])
    return json.dumps(
        {
            "answer": guarded.answer,
            "citations": citations,
            "guard": {"unsupported": guarded.unsupported, "warnings": guarded.warnings},
        },
        ensure_ascii=False,
    )


async def _classify(c, query: str):
    return await classify_intent(query, _jev(c), min_confidence=c.settings.jev_intent_min_confidence)


async def _score_relevance(c, query: str, res: RetrievalResult) -> list[ArticleRelevance]:
    jev = _jev(c) if c.settings.jev_relevance_enabled else None
    judged = await judge_articles(query, res.items, jev, min_noul=c.settings.jev_relevance_min_noul)
    for it, j in zip(res.items, judged, strict=True):
        it.relevance_noul = j.noul
    return judged


@router.post("/search")
async def search(request: Request, body: QueryRequest) -> dict:
    c = request.app.state.c
    classified = await _classify(c, body.query)
    if classified.intent is not QueryIntent.RAG_QUERY:
        return {
            "query": body.query,
            "items": [],
            "timings_ms": {},
            "subgraph": None,
            "intent": classified.intent.value,
            "message": direct_answer(classified.intent),
        }
    res = await Retriever(c).retrieve(body.query, _opts(body))
    await _score_relevance(c, body.query, res)
    payload = res.to_dict()
    payload["intent"] = QueryIntent.RAG_QUERY.value
    return payload


@router.post("/ask")
async def ask(request: Request, body: QueryRequest):
    c = request.app.state.c

    async def gen():
        try:
            classified = await _classify(c, body.query)
            reply = direct_answer(classified.intent)
            if reply is not None:
                yield {"event": "done", "data": _done(reply, [], [])}
                return
            res = await Retriever(c).retrieve(body.query, _opts(body))
            judged = await _score_relevance(c, body.query, res)
            yield {"event": "retrieval", "data": json.dumps(res.to_dict(), ensure_ascii=False, default=str)}
            grounded = [j.article for j in judged if j.relevant]
            citations = [{"n": i + 1, "uid": it.uid, "citation": it.citation, "caption": it.caption}
                         for i, it in enumerate(grounded)]
            if not c.llm.enabled:
                msg = "LLM chưa được cấu hình (LLM_MODEL). Chỉ trả về kết quả truy xuất."
                yield {"event": "done", "data": _done(msg, grounded, citations)}
                return
            if not grounded:
                msg = "参照できる条文が見つかりませんでした。"
                yield {"event": "done", "data": _done(msg, [], [])}
                return
            answer = []
            async for tok in c.llm.stream(build_messages(body.query, grounded, c.settings.prompts_dir)):
                if await request.is_disconnected():
                    return
                answer.append(tok)
                yield {"event": "token", "data": json.dumps({"t": tok}, ensure_ascii=False)}
            yield {"event": "done", "data": _done("".join(answer), grounded, citations)}
        except Exception as e:
            log.exception("ask failed")
            yield {"event": "error", "data": json.dumps({"message": str(e)[:500]}, ensure_ascii=False)}

    return EventSourceResponse(gen(), ping=15)
