"""Qdrant – lưu vector chunk (dense 768-d, cosine) + payload để filter.

Point id = uuid5(chunk_uid). Payload chứa article_uid (khoá chung với Neo4j / PostgreSQL).
Phase 1: thêm sparse vector "bm25" (token Sudachi) vào cùng collection.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from qdrant_client import AsyncQdrantClient, models

from jplegal.core.models import Chunk

_NS = uuid.UUID("6f1c2a7e-2f3b-4c55-9a43-6a1d6c0c9f10")
DENSE = "dense"


def point_id(chunk_uid: str) -> str:
    return str(uuid.uuid5(_NS, chunk_uid))


@dataclass
class DenseHit:
    article_uid: str
    chunk_uid: str
    score: float
    payload: dict


class QdrantStore:
    def __init__(self, url: str, collection: str, dim: int, api_key: str | None = None,
                 client: AsyncQdrantClient | None = None):
        self.client = client or AsyncQdrantClient(url=url, api_key=api_key or None, timeout=60)
        self.collection = collection
        self.dim = dim

    async def close(self) -> None:
        await self.client.close()

    async def ensure_collection(self) -> None:
        if not await self.client.collection_exists(self.collection):
            await self.client.create_collection(
                self.collection,
                vectors_config={DENSE: models.VectorParams(size=self.dim, distance=models.Distance.COSINE)},
            )
            for field in ("law_id", "article_uid", "law_type", "source"):
                await self.client.create_payload_index(self.collection, field, models.PayloadSchemaType.KEYWORD)

    async def delete_law(self, law_id: str) -> None:
        await self.client.delete(
            self.collection,
            points_selector=models.FilterSelector(filter=_match("law_id", [law_id])),
            wait=True,
        )

    async def upsert_chunks(self, chunks: list[Chunk], vectors: list[list[float]], extra: dict | None = None,
                            batch: int = 128) -> None:
        extra = extra or {}
        points = [
            models.PointStruct(
                id=point_id(c.chunk_uid),
                vector={DENSE: v},
                payload={
                    "chunk_uid": c.chunk_uid,
                    "article_uid": c.article_uid,
                    "law_id": c.law_id,
                    "law_title": c.law_title,
                    "article_key": c.article_key,
                    "article_title": c.article_title,
                    "caption": c.caption,
                    "path": c.path,
                    "part": c.part,
                    "text": c.text,
                    **extra,
                },
            )
            for c, v in zip(chunks, vectors, strict=True)
        ]
        for i in range(0, len(points), batch):
            await self.client.upsert(self.collection, points=points[i : i + batch], wait=True)

    async def search(self, vector: list[float], limit: int, law_ids: list[str] | None = None) -> list[DenseHit]:
        flt = _match("law_id", law_ids) if law_ids else None
        res = await self.client.query_points(
            self.collection, query=vector, using=DENSE, limit=limit, query_filter=flt, with_payload=True,
        )
        return [
            DenseHit(article_uid=p.payload["article_uid"], chunk_uid=p.payload["chunk_uid"], score=p.score,
                     payload=p.payload)
            for p in res.points
        ]

    async def vectors_for_articles(self, article_uids: list[str]) -> dict[str, list[list[float]]]:
        """Lấy vector của mọi chunk thuộc các article (để chấm cosine cho node mở rộng từ graph)."""
        if not article_uids:
            return {}
        out: dict[str, list[list[float]]] = {}
        offset = None
        while True:
            pts, offset = await self.client.scroll(
                self.collection, scroll_filter=_match("article_uid", article_uids), limit=256,
                with_vectors=[DENSE], with_payload=["article_uid"], offset=offset,
            )
            for p in pts:
                vec = p.vector[DENSE] if isinstance(p.vector, dict) else p.vector
                out.setdefault(p.payload["article_uid"], []).append(vec)
            if offset is None:
                break
        return out

    async def count(self) -> int:
        return (await self.client.count(self.collection, exact=False)).count


def _match(field: str, values: list[str]) -> models.Filter:
    return models.Filter(must=[models.FieldCondition(key=field, match=models.MatchAny(any=list(values)))])
