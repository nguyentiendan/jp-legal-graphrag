"""Retrieval: Dense + Sparse/BM25 (Qdrant hybrid) + Graph expansion (Neo4j) → fusion → Rerank (ruri-v3-reranker).

1. Embed câu hỏi (prefix 検索クエリ: ) + Sudachi/BM25 sparse vector
2. First stage (Qdrant): dense | sparse | hybrid (2 prefetch + RRF/DBSF trong Qdrant) → gộp theo article (max)
3. Seed = top seed_k article → mở rộng 1-hop REFERS_TO / 準用 / 委任 (2 chiều)
   - node Article: chấm cosine(query, vector chunk của article) → xếp hạng
   - node Law (委任 tới 施行令/施行規則): dense search giới hạn trong law đó (top delegated_per_law)
4. Fusion: "slots" (mặc định) – dense là chính, graph bổ sung tối đa graph_slots điều mới;
   khi rerank: pool = dense top rerank_top_n ∪ graph candidates, cross-encoder quyết định thứ tự.
   "rrf" – weighted RRF (w_dense, w_graph, rrf_k) để so sánh.
5. Rerank top-N bằng cross-encoder → final_k
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass, field

import numpy as np

from jplegal.ingest.normalize import display_article
from jplegal.retrieval.fusion import slot_fusion, weighted_rrf


@dataclass
class RetrievalOptions:
    use_graph: bool = True
    use_rerank: bool = True
    use_sparse: bool | None = None  # None = theo SPARSE_ENABLED
    law_ids: list[str] | None = None
    final_k: int | None = None
    first_stage: str | None = None  # dense | sparse | hybrid (None = tự chọn theo use_sparse)
    fusion: str | None = None  # rrf | dbsf (None = HYBRID_FUSION)


@dataclass
class RetrievedArticle:
    uid: str
    law_id: str
    law_title: str
    article_key: str
    title: str
    caption: str
    path: str
    text: str
    sources: list[str] = field(default_factory=list)  # dense / sparse / graph
    dense_rank: int | None = None
    dense_score: float | None = None
    sparse_rank: int | None = None
    sparse_score: float | None = None
    hybrid_rank: int | None = None
    graph_rank: int | None = None
    graph_score: float | None = None
    graph_via: list[dict] = field(default_factory=list)  # [{from, rel}]
    rrf_score: float = 0.0
    rerank_score: float | None = None

    @property
    def citation(self) -> str:
        return f"{self.law_title} {display_article(self.article_key)}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["citation"] = self.citation
        return d


@dataclass
class RetrievalResult:
    query: str
    items: list[RetrievedArticle]
    timings_ms: dict[str, float]
    subgraph: dict | None = None
    first_stage: str = "dense"

    def to_dict(self) -> dict:
        return {"query": self.query, "items": [i.to_dict() for i in self.items], "timings_ms": self.timings_ms,
                "subgraph": self.subgraph, "first_stage": self.first_stage}


def _cos(q: np.ndarray, vecs: list[list[float]]) -> float:
    m = np.asarray(vecs, dtype=np.float32)
    m /= np.linalg.norm(m, axis=1, keepdims=True) + 1e-9
    return float((m @ q).max())


def _by_article(hits) -> dict[str, float]:
    out: dict[str, float] = {}
    for h in hits:
        out[h.article_uid] = max(out.get(h.article_uid, -1e9), h.score)
    return out


class Retriever:
    def __init__(self, c):
        self.c = c
        self.s = c.settings

    async def retrieve(self, query: str, opts: RetrievalOptions | None = None) -> RetrievalResult:
        opts = opts or RetrievalOptions()
        s, t = self.s, {}
        t0 = time.perf_counter()

        qv = await self.c.models.embed_query(query)
        qn = np.asarray(qv, dtype=np.float32)
        qn /= np.linalg.norm(qn) + 1e-9
        t["embed"] = (time.perf_counter() - t0) * 1000

        # ---- First stage: dense / sparse / hybrid
        t1 = time.perf_counter()
        use_sparse = s.sparse_enabled if opts.use_sparse is None else opts.use_sparse
        stage = opts.first_stage or ("hybrid" if use_sparse else "dense")
        if stage != "dense" and not await self.c.qdrant.has_sparse():
            stage = "dense"  # collection chưa có sparse vector (chưa chạy reindex-sparse)
        sv = self.c.sparse.encode_query(query) if stage != "dense" else None
        if stage != "dense" and not sv:
            stage = "dense"
        lim = s.dense_top_k * 3
        if stage == "dense":
            d_hits, s_hits = await self.c.qdrant.search(qv, limit=lim, law_ids=opts.law_ids), []
            hits = d_hits
        elif stage == "sparse":
            d_hits, s_hits = [], await self.c.qdrant.search_sparse(sv, limit=lim, law_ids=opts.law_ids)
            hits = s_hits
        else:
            # thứ hạng do Qdrant fusion quyết định; 2 truy vấn riêng chỉ để hiển thị nhánh nào tìm thấy (vài ms)
            d_hits, s_hits, hits = await asyncio.gather(
                self.c.qdrant.search(qv, limit=lim, law_ids=opts.law_ids),
                self.c.qdrant.search_sparse(sv, limit=lim, law_ids=opts.law_ids),
                self.c.qdrant.search_hybrid(
                    qv, sv, limit=lim, law_ids=opts.law_ids, fusion=opts.fusion or s.hybrid_fusion,
                    rrf_k=s.hybrid_rrf_k, weights=(s.hybrid_w_dense, s.hybrid_w_sparse)),
            )
        dense = _by_article(d_hits)
        sparse = _by_article(s_hits)
        first = _by_article(hits)
        ranked = sorted(first, key=first.get, reverse=True)[: s.dense_top_k]  # type: ignore[arg-type]
        d_rank_all = {u: i + 1 for i, u in enumerate(sorted(dense, key=dense.get, reverse=True))}  # type: ignore[arg-type]
        s_rank_all = {u: i + 1 for i, u in enumerate(sorted(sparse, key=sparse.get, reverse=True))}  # type: ignore[arg-type]
        t[stage] = (time.perf_counter() - t1) * 1000
        final_k = opts.final_k or s.final_k

        # ---- Graph expansion
        graph_ranked: list[str] = []
        graph_scores: dict[str, float] = {}
        via: dict[str, list[dict]] = {}
        edges_for_view: list[dict] = []
        if opts.use_graph and ranked:
            t2 = time.perf_counter()
            seeds = ranked[: s.seed_k]
            # chỉ loại các điều đã nằm trong top final_k – điều first stage xếp hạng thấp vẫn có thể được graph kéo lên
            dense_set = set(ranked[:final_k])
            edges = await self.c.neo4j.expand(seeds)
            art_cands: set[str] = set()
            law_cands: dict[str, list[dict]] = {}
            for e in edges:
                info = {"from": e.src, "rel": e.rel, "direction": "out" if e.outgoing else "in"}
                edges_for_view.append({"source": e.src if e.outgoing else e.dst,
                                       "target": e.dst if e.outgoing else e.src, "rel": e.rel})
                if e.dst_kind == "Article":
                    if e.dst in dense_set:  # chỉ lấy điều mà dense chưa tìm thấy
                        continue
                    art_cands.add(e.dst)
                    via.setdefault(e.dst, []).append(info)
                elif e.outgoing and e.rel == "DELEGATES_TO":
                    law_cands.setdefault(e.dst, []).append(info)
            if opts.law_ids:
                art_cands = {u for u in art_cands if u.split("#")[0] in opts.law_ids}
            vecs = await self.c.qdrant.vectors_for_articles(sorted(art_cands))
            for uid, vs in vecs.items():
                graph_scores[uid] = _cos(qn, vs)
            # 委任: tìm điều liên quan nhất trong 施行令/施行規則 được uỷ quyền
            for law_id, infos in list(law_cands.items())[:5]:
                for h in await self.c.qdrant.search(qv, limit=s.delegated_per_law * 2, law_ids=[law_id]):
                    if h.article_uid in dense_set:
                        continue
                    if h.score > graph_scores.get(h.article_uid, -1):
                        graph_scores[h.article_uid] = h.score
                        via.setdefault(h.article_uid, []).extend(infos[:1])
            graph_ranked = sorted(graph_scores, key=graph_scores.get, reverse=True)[: s.graph_max]  # type: ignore[arg-type]
            t["graph"] = (time.perf_counter() - t2) * 1000

        # ---- Fusion
        dense_ranked = ranked
        do_rerank = opts.use_rerank and s.rerank_enabled
        if s.fusion_mode == "rrf":
            fused = weighted_rrf({"dense": dense_ranked, "graph": graph_ranked},
                                 {"dense": s.w_dense, "graph": s.w_graph}, k=s.rrf_k)
            cands = fused[: s.rerank_top_n + len(graph_ranked) if do_rerank else final_k]
        elif do_rerank:
            pool = list(dict.fromkeys(dense_ranked[: s.rerank_top_n] + graph_ranked))
            cands = [(u, 1.0 / (i + 1)) for i, u in enumerate(pool)]
        else:
            cands = slot_fusion(dense_ranked, graph_ranked, final_k, s.graph_slots)[:final_k]
        details = await self.c.neo4j.get_articles([u for u, _ in cands])
        # fallback cho article chưa có trong Neo4j (vd. lỗi ghi) → lấy từ payload Qdrant
        payloads = {h.article_uid: h.payload for h in (*hits, *d_hits, *s_hits)}

        items: list[RetrievedArticle] = []
        h_rank = {u: i + 1 for i, u in enumerate(dense_ranked)}
        d_rank = {u: r for u, r in d_rank_all.items() if r <= s.dense_top_k}
        s_rank = {u: r for u, r in s_rank_all.items() if r <= s.dense_top_k}
        if stage == "dense":
            d_rank = h_rank
        g_rank = {u: i + 1 for i, u in enumerate(graph_ranked)}
        for uid, score in cands:
            d = details.get(uid) or payloads.get(uid)
            if not d:
                continue
            items.append(RetrievedArticle(
                uid=uid, law_id=d["law_id"], law_title=d.get("law_title", ""), article_key=d["article_key"],
                title=d.get("title") or d.get("article_title", ""), caption=d.get("caption", ""),
                path=d.get("path", ""), text=d.get("text", ""),
                sources=[x for x, r in (("dense", d_rank), ("sparse", s_rank), ("graph", g_rank)) if uid in r],
                dense_rank=d_rank.get(uid), dense_score=dense.get(uid),
                sparse_rank=s_rank.get(uid), sparse_score=sparse.get(uid),
                hybrid_rank=h_rank.get(uid) if stage == "hybrid" else None,
                graph_rank=g_rank.get(uid), graph_score=graph_scores.get(uid), graph_via=via.get(uid, [])[:3],
                rrf_score=score,
            ))

        # ---- Rerank
        if opts.use_rerank and s.rerank_enabled and items:
            t3 = time.perf_counter()
            docs = [f"{i.law_title} {i.title}{i.caption}\n{i.text}"[: s.rerank_max_chars] for i in items]
            for idx, sc in await self.c.models.rerank(query, docs):
                items[idx].rerank_score = sc
            items.sort(key=lambda x: x.rerank_score if x.rerank_score is not None else -1e9, reverse=True)
            t["rerank"] = (time.perf_counter() - t3) * 1000

        items = items[:final_k]
        keep = {i.uid for i in items}
        sub = {
            "nodes": [{"id": i.uid, "label": i.citation, "caption": i.caption, "seed": True, "kind": "Article",
                       "sources": i.sources} for i in items],
            "edges": list({(e["source"], e["target"], e["rel"]): e for e in edges_for_view
                           if e["source"] in keep and e["target"] in keep}.values()),
        }
        t["total"] = (time.perf_counter() - t0) * 1000
        return RetrievalResult(query=query, items=items,
                               timings_ms={k: round(v, 1) for k, v in t.items()}, first_stage=stage,
                               subgraph=sub)
