"""Đánh giá retrieval theo mục 7 tài liệu #19: Recall@1/5/10, MRR@10, nDCG@10.

queries.jsonl: {"qid": "...", "question": "...", "relevant": ["322AC0000000049#32", ...]}
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from jplegal.retrieval.pipeline import RetrievalOptions, Retriever

CONFIGS = {
    "dense": RetrievalOptions(use_graph=False, use_rerank=False, final_k=10),
    "dense+graph": RetrievalOptions(use_graph=True, use_rerank=False, final_k=10),
    "dense+rerank": RetrievalOptions(use_graph=False, use_rerank=True, final_k=10),
    "dense+graph+rerank": RetrievalOptions(use_graph=True, use_rerank=True, final_k=10),
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
            "recall@10": recall_at(ranked, rel, 10), "mrr@10": mrr_at(ranked, rel), "ndcg@10": ndcg_at(ranked, rel)}


async def run_eval(c, path: Path) -> dict:
    qs = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    r = Retriever(c)
    report: dict = {"n_queries": len(qs), "configs": {}, "per_query": []}
    sums = {name: {} for name in CONFIGS}
    for q in qs:
        rel = set(q["relevant"])
        row = {"qid": q["qid"], "question": q["question"]}
        for name, opts in CONFIGS.items():
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
