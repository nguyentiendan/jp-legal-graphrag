"""Weighted Reciprocal Rank Fusion: score(d) = Σ_i w_i / (k + rank_i(d)), ranks start at 1."""

from __future__ import annotations


def weighted_rrf(rankings: dict[str, list[str]], weights: dict[str, float], k: int = 60) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for name, ids in rankings.items():
        w = weights.get(name, 1.0)
        seen: set[str] = set()
        for rank, doc_id in enumerate(ids, start=1):
            if doc_id in seen:
                continue
            seen.add(doc_id)
            scores[doc_id] = scores.get(doc_id, 0.0) + w / (k + rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def slot_fusion(dense: list[str], graph: list[str], final_k: int, slots: int) -> list[tuple[str, float]]:
    """Dense (first stage) is the main list; graph adds at most `slots` articles missing from top `final_k`
    (a first-stage article ranked below final_k can also be pulled up).

    Order: dense[: final_k - slots] → graph (new) → remaining dense.
    Returned scores are 1/rank for display (no absolute meaning).
    Rationale: with Ruri v3, dense is already very strong; additive RRF lets articles that are
    "both low-ranked by dense and graph neighbors" overtake the correct one (measured on eval/queries.jsonl).
    Graph's role is to supply related context.
    """
    top = set(dense[:final_k])
    new_graph = [g for g in dict.fromkeys(graph) if g not in top][: max(0, slots)]
    head = [d for d in dense if d not in new_graph][: max(0, final_k - len(new_graph))]
    order = head + new_graph + [d for d in dense if d not in head and d not in new_graph]
    return [(u, 1.0 / (i + 1)) for i, u in enumerate(order)]
