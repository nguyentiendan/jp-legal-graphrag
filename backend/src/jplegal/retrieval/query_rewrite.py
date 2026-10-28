"""Colloquial → legal-term query expansion (rule-based, deterministic).

Users ask in everyday words (残業代, クビ, 有給, 36協定) while statutes use formal
terms (割増賃金, 解雇, 年次有給休暇, 時間外・休日労働). Every pair below is grounded
in the project's own eval sets (`backend/eval/queries*.jsonl`): the left side is
how questions phrase it, the right side is the wording of the relevant articles.

The expanded query is used for embedding + BM25 only. The original question is
kept for display, relevance judgement, and answer generation.
"""

from __future__ import annotations

# Insertion order = match priority (longer colloquial forms first).
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "残業代": ("割増賃金",),
    "サービス残業": ("時間外労働",),
    "残業": ("時間外労働",),
    "36協定": ("時間外労働", "休日労働"),
    "三六協定": ("時間外労働", "休日労働"),
    "有給": ("年次有給休暇",),
    "クビ": ("解雇",),
    "首切り": ("解雇",),
    "産休": ("産前産後休業",),
    "育休": ("育児休業",),
    "給料": ("賃金",),
}


def expand_query(query: str) -> str:
    """Append formal legal terms for any colloquial term found in the query.

    Terms already present in the query are not duplicated. Returns the query
    unchanged when nothing matches.
    """
    extra: list[str] = []
    for colloquial, formal_terms in _SYNONYMS.items():
        if colloquial not in query:
            continue
        for term in formal_terms:
            if term not in query and term not in extra:
                extra.append(term)
    if not extra:
        return query
    return f"{query} {' '.join(extra)}"
