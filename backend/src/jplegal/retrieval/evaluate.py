"""Đánh giá retrieval theo mục 7 tài liệu #19: Recall@1/5/10, MRR@10, nDCG@10 (+ All@10 cho câu multi-hop).

queries.jsonl: {"qid": "...", "question": "...", "relevant": ["322AC0000000049#32", ...]}
    eval/queries.jsonl           – 20 câu "1 điều trả lời được"
    eval/queries_multihop.jsonl  – 38 câu cần 2–3 điều (luật + 施行規則/政令 được uỷ quyền, điều dẫn chiếu)
All@10 = tỉ lệ câu hỏi mà *mọi* điều cần thiết đều nằm trong top 10.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from jplegal.retrieval.pipeline import RetrievalOptions, Retriever


def _o(stage: str, graph: bool, rerank: bool, fusion: str | None = None) -> RetrievalOptions:
    return RetrievalOptions(first_stage=stage, use_graph=graph, use_rerank=rerank, fusion=fusion, final_k=10)


CONFIGS = {
    "dense": _o("dense", False, False),
    "bm25": _o("sparse", False, False),
    "hybrid(rrf)": _o("hybrid", False, False, "rrf"),
    "hybrid(dbsf)": _o("hybrid", False, False, "dbsf"),
    "dense+graph": _o("dense", True, False),
    "hybrid(rrf)+graph": _o("hybrid", True, False, "rrf"),
    "hybrid(dbsf)+graph": _o("hybrid", True, False, "dbsf"),
    "dense+rerank": _o("dense", False, True),
    "dense+graph+rerank": _o("dense", True, True),
    "hybrid(rrf)+graph+rerank": _o("hybrid", True, True, "rrf"),
    "hybrid(dbsf)+graph+rerank": _o("hybrid", True, True, "dbsf"),
}


def recall_at(ranked: list[str], rel: set[str], k: int) -> float:
    return len(set(ranked[:k]) & rel) / len(rel) if rel else 0.0


def mrr_at(ranked: list[str], rel: set[str], k: int = 10) -> float:
    for i, d in enumerate(ranked[:k], 1):
        if d in rel:
            return 1.0 / i
    return 0.0


def ndcg_at(ranked: list[str], rel: set[str], k: int = 10) -> float:
    dcg = sum(1.0 / math.log2(i + 1) for i, d in enumerate(ranked[:k], 1) if d in rel)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(rel), k) + 1))
    return dcg / idcg if idcg else 0.0


def metrics(ranked: list[str], rel: set[str]) -> dict[str, float]:
    return {"recall@1": recall_at(ranked, rel, 1), "recall@5": recall_at(ranked, rel, 5),
            "recall@10": recall_at(ranked, rel, 10), "mrr@10": mrr_at(ranked, rel), "ndcg@10": ndcg_at(ranked, rel),
            "all@10": float(rel <= set(ranked[:10]))}


async def run_eval(c, path: Path, configs: list[str] | None = None) -> dict:
    qs = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    r = Retriever(c)
    cfgs = {k: v for k, v in CONFIGS.items() if not configs or k in configs}
    report: dict = {"queries": str(path), "n_queries": len(qs), "configs": {}, "per_query": []}
    sums = {name: {} for name in cfgs}
    for q in qs:
        rel = set(q["relevant"])
        row = {"qid": q["qid"], "question": q["question"]}
        for name, opts in cfgs.items():
            res = await r.retrieve(q["question"], opts)
            ranked = [i.uid for i in res.items]
            m = metrics(ranked, rel)
            row[name] = {"top5": ranked[:5], **m}
            for k, v in m.items():
                sums[name][k] = sums[name].get(k, 0.0) + v
        report["per_query"].append(row)
    n = max(1, len(qs))
    report["configs"] = {name: {k: round(v / n, 4) for k, v in s.items()} for name, s in sums.items()}
    return report
