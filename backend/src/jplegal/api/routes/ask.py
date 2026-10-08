"""/api/search (chỉ retrieval) và /api/ask (retrieval + LLM, stream SSE).

SSE events của /api/ask:
    event: retrieval   data: {items, timings_ms, subgraph}
    event: token       data: {"t": "..."}
    event: done        data: {"answer": "...", "citations": [...]}
    event: error       data: {"message": "..."}
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from jplegal.retrieval.answer import build_messages
from jplegal.retrieval.pipeline import RetrievalOptions, Retriever

router = APIRouter(tags=["retrieval"])
log = logging.getLogger(__name__)


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    law_ids: list[str] | None = None
    use_graph: bool = True
    use_rerank: bool = True
    top_k: int | None = Field(None, ge=1, le=30)


def _opts(b: QueryRequest) -> RetrievalOptions:
    return RetrievalOptions(use_graph=b.use_graph, use_rerank=b.use_rerank, law_ids=b.law_ids or None,
                            final_k=b.top_k)


@router.post("/search")
async def search(request: Request, body: QueryRequest) -> dict:
    res = await Retriever(request.app.state.c).retrieve(body.query, _opts(body))
    return res.to_dict()


@router.post("/ask")
async def ask(request: Request, body: QueryRequest):
    c = request.app.state.c

    async def gen():
        try:
            res = await Retriever(c).retrieve(body.query, _opts(body))
            yield {"event": "retrieval", "data": json.dumps(res.to_dict(), ensure_ascii=False, default=str)}
            citations = [{"n": i + 1, "uid": it.uid, "citation": it.citation, "caption": it.caption}
                         for i, it in enumerate(res.items)]
            if not c.llm.enabled:
                msg = "LLM chưa được cấu hình (LLM_MODEL). Chỉ trả về kết quả truy xuất."
                yield {"event": "done", "data": json.dumps({"answer": msg, "citations": citations}, ensure_ascii=False)}
                return
            if not res.items:
                msg = "参照できる条文が見つかりませんでした。"
                yield {"event": "done", "data": json.dumps({"answer": msg, "citations": []}, ensure_ascii=False)}
                return
            answer = []
            async for tok in c.llm.stream(build_messages(body.query, res.items, c.settings.prompts_dir)):
                if await request.is_disconnected():
                    return
                answer.append(tok)
                yield {"event": "token", "data": json.dumps({"t": tok}, ensure_ascii=False)}
            yield {"event": "done",
                   "data": json.dumps({"answer": "".join(answer), "citations": citations}, ensure_ascii=False)}
        except Exception as e:
            log.exception("ask failed")
            yield {"event": "error", "data": json.dumps({"message": str(e)[:500]}, ensure_ascii=False)}

    return EventSourceResponse(gen(), ping=15)
