"""Qdrant – each chunk = 1 point with 2 named vectors:
    dense  : Ruri v3 768-d, cosine
    bm25   : sparse vector (Sudachi + BM25 tf weights), modifier=IDF → Qdrant computes IDF itself
+ payload for filtering. Point id = uuid5(chunk_uid). Payload holds article_uid (shared key with Neo4j / PostgreSQL).

Hybrid search (dense + sparse) runs in 1 request: 2 prefetches + Qdrant's RRF / DBSF fusion.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from qdrant_client import AsyncQdrantClient, models

from jplegal.core.models import Chunk

if TYPE_CHECKING:
    from jplegal.retrieval.sparse import SparseVec

_NS = uuid.UUID("6f1c2a7e-2f3b-4c55-9a43-6a1d6c0c9f10")
DENSE = "dense"
SPARSE = "bm25"
log = logging.getLogger(__name__)
PAYLOAD_INDEXES = ("law_id", "article_uid", "law_type", "source")


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
        self._has_sparse: bool | None = None

    async def close(self) -> None:
        await self.client.close()

    async def _create(self, name: str) -> None:
        await self.client.create_collection(
            name,
            vectors_config={DENSE: models.VectorParams(size=self.dim, distance=models.Distance.COSINE)},
            sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)},
        )
        for field in PAYLOAD_INDEXES:
            await self.client.create_payload_index(name, field, models.PayloadSchemaType.KEYWORD)

    async def ensure_collection(self) -> None:
        if not await self.client.collection_exists(self.collection):
            await self._create(self.collection)
        self._has_sparse = None

    async def has_sparse(self) -> bool:
        """Whether the collection already has the "bm25" sparse vector (P0-created ones don't → need reindex-sparse)."""
        if getattr(self, "_has_sparse", None) is None:
            try:
                info = await self.client.get_collection(self.collection)
                self._has_sparse = SPARSE in (info.config.params.sparse_vectors or {})
            except Exception:  # collection doesn't exist yet
                return False
        return bool(self._has_sparse)

    async def delete_law(self, law_id: str) -> None:
        await self.client.delete(
            self.collection,
            points_selector=models.FilterSelector(filter=_match("law_id", [law_id])),
            wait=True,
        )

    async def upsert_chunks(self, chunks: list[Chunk], vectors: list[list[float]], extra: dict | None = None,
                            batch: int = 128, sparse: list[SparseVec] | None = None) -> None:
        extra = extra or {}
        use_sparse = sparse is not None and await self.has_sparse()

        def vec(i: int, v: list[float]) -> dict:
            out: dict = {DENSE: v}
            if use_sparse and sparse[i]:  # type: ignore[index]
                out[SPARSE] = models.SparseVector(indices=sparse[i].indices, values=sparse[i].values)  # type: ignore[index]
            return out

        points = [
            models.PointStruct(
                id=point_id(c.chunk_uid),
                vector=vec(i, v),
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
            for i, (c, v) in enumerate(zip(chunks, vectors, strict=True))
        ]
        for i in range(0, len(points), batch):
            await self.client.upsert(self.collection, points=points[i : i + batch], wait=True)

    async def search(self, vector: list[float], limit: int, law_ids: list[str] | None = None) -> list[DenseHit]:
        flt = _match("law_id", law_ids) if law_ids else None
        res = await self.client.query_points(
            self.collection, query=vector, using=DENSE, limit=limit, query_filter=flt, with_payload=True,
        )
        return _hits(res.points)

    async def search_sparse(self, svec: SparseVec, limit: int, law_ids: list[str] | None = None) -> list[DenseHit]:
        if not svec:
            return []
        flt = _match("law_id", law_ids) if law_ids else None
        res = await self.client.query_points(
            self.collection, query=models.SparseVector(indices=svec.indices, values=svec.values), using=SPARSE,
            limit=limit, query_filter=flt, with_payload=True,
        )
        return _hits(res.points)

    async def search_hybrid(self, vector: list[float], svec: SparseVec, limit: int, law_ids: list[str] | None = None,
                            fusion: str = "rrf", prefetch_limit: int | None = None, rrf_k: int = 60,
                            weights: tuple[float, float] | None = None) -> list[DenseHit]:
        """Dense + sparse in 1 request: 2 prefetches → Qdrant fusion (rrf | dbsf)."""
        if not svec:
            return await self.search(vector, limit, law_ids)
        flt = _match("law_id", law_ids) if law_ids else None
        pl = prefetch_limit or limit
        prefetch = [
            models.Prefetch(query=vector, using=DENSE, limit=pl, filter=flt),
            models.Prefetch(query=models.SparseVector(indices=svec.indices, values=svec.values), using=SPARSE,
                            limit=pl, filter=flt),
        ]
        if fusion == "dbsf":
            q: models.Query = models.FusionQuery(fusion=models.Fusion.DBSF)
        elif weights and weights != (1.0, 1.0):
            q = models.RrfQuery(rrf=models.Rrf(k=rrf_k, weights=list(weights)))
        else:
            q = models.RrfQuery(rrf=models.Rrf(k=rrf_k))
        res = await self.client.query_points(self.collection, prefetch=prefetch, query=q, limit=limit,
                                             with_payload=True)
        return _hits(res.points)

    # ------------------------------------------------------------------ sparse maintenance
    async def reindex_sparse(self, encode: Callable[[dict], SparseVec], batch: int = 256,
                             progress: Callable[[int, str], Awaitable[None]] | None = None) -> dict:
        """Recompute sparse vectors for all points.

        Old collections (P0, no "bm25") → create a temp collection with dense + sparse, copy dense + payload over,
        delete the old collection, recreate it with the new schema and copy back (Qdrant can't add a named
        vector to an existing collection).
        """
        migrated = False
        if not await self.has_sparse():
            await self._migrate_schema(progress)
            migrated = True
        total = (await self.client.count(self.collection, exact=True)).count
        done, offset = 0, None
        while True:
            pts, offset = await self.client.scroll(self.collection, limit=batch, offset=offset, with_payload=True,
                                                   with_vectors=False)
            if not pts:
                break
            upd = []
            for p in pts:
                sv = encode(p.payload or {})
                upd.append(models.PointVectors(
                    id=p.id, vector={SPARSE: models.SparseVector(indices=sv.indices, values=sv.values)}))
            await self.client.update_vectors(self.collection, points=upd, wait=True)
            done += len(pts)
            if progress:
                await progress(int(100 * done / max(1, total)), f"BM25 {done}/{total}")
            if offset is None:
                break
        return {"points": done, "migrated": migrated}

    async def _migrate_schema(self, progress) -> None:
        tmp = f"{self.collection}__migrate"
        log.warning("Qdrant: collection %s has no sparse vector – migrating schema (via %s)", self.collection, tmp)
        if await self.client.collection_exists(tmp):
            await self.client.delete_collection(tmp)
        await self._create(tmp)
        await self._copy(self.collection, tmp, progress, "copy to temp collection")
        await self.client.delete_collection(self.collection)
        await self._create(self.collection)
        await self._copy(tmp, self.collection, progress, "copy back to new collection")
        await self.client.delete_collection(tmp)
        self._has_sparse = True

    async def _copy(self, src: str, dst: str, progress, label: str, batch: int = 256) -> None:
        offset, n = None, 0
        while True:
            pts, offset = await self.client.scroll(src, limit=batch, offset=offset, with_payload=True,
                                                   with_vectors=True)
            if not pts:
                break
            out = []
            for p in pts:
                v = p.vector if isinstance(p.vector, dict) else {DENSE: p.vector}
                out.append(models.PointStruct(id=p.id, vector=dict(v), payload=p.payload))
            await self.client.upsert(dst, points=out, wait=True)
            n += len(pts)
            if progress:
                await progress(0, f"{label}: {n}")
            if offset is None:
                break

    async def vectors_for_articles(self, article_uids: list[str]) -> dict[str, list[list[float]]]:
        """Fetch vectors of all chunks in given articles (to cosine-score graph-expanded nodes)."""
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


def _hits(points) -> list[DenseHit]:
    return [
        DenseHit(article_uid=p.payload["article_uid"], chunk_uid=p.payload["chunk_uid"], score=p.score,
                 payload=p.payload)
        for p in points
    ]


def _match(field: str, values: list[str]) -> models.Filter:
    return models.Filter(must=[models.FieldCondition(key=field, match=models.MatchAny(any=list(values)))])
