"""Client for model-server (ruri-v3-310m embedding + ruri-v3-reranker-310m)."""

from __future__ import annotations

import asyncio

import httpx

from jplegal.core.config import Settings


class ModelServerClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self.http = httpx.AsyncClient(base_url=settings.model_server_url, timeout=settings.model_server_timeout)

    async def close(self) -> None:
        await self.http.aclose()

    async def _post(self, path: str, payload: dict, retries: int = 3) -> dict:
        for attempt in range(retries + 1):
            try:
                r = await self.http.post(path, json=payload)
                r.raise_for_status()
                return r.json()
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                status = getattr(getattr(e, "response", None), "status_code", None)
                if attempt >= retries or (status is not None and status < 500):
                    raise
                await asyncio.sleep(2 ** attempt)
        raise RuntimeError("unreachable")

    async def embed(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        prefix = self.s.query_prefix if is_query else self.s.doc_prefix
        out: list[list[float]] = []
        bs = self.s.embed_batch_size
        for i in range(0, len(texts), bs):
            batch = [prefix + t for t in texts[i : i + bs]]
            data = await self._post("/v1/embeddings", {"input": batch, "model": "ruri-v3-310m"})
            out.extend(d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"]))
        return out

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed([text], is_query=True))[0]

    async def rerank(self, query: str, documents: list[str], top_n: int | None = None) -> list[tuple[int, float]]:
        if not documents:
            return []
        data = await self._post(
            "/v1/rerank",
            {"query": query, "documents": documents, "top_n": top_n or len(documents), "model": "ruri-v3-reranker-310m"},
        )
        return [(r["index"], float(r["relevance_score"])) for r in data["results"]]

    async def health(self) -> dict:
        r = await self.http.get("/health")
        r.raise_for_status()
        return r.json()
