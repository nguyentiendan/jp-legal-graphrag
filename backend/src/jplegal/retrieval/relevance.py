"""Task 2: document relevance with Jev Noul, after retrieval.

Independent of intent. One Noul per retrieved article in a single System One call.
Does not call the Ruri reranker.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from jplegal.retrieval.pipeline import RetrievedArticle

_MAX_CHARS = 800
# Statutory exceptions (ただし書) and delegation clauses (政令で定める) usually sit
# at the end of an article, so truncation keeps the tail, not just the head.
_HEAD_CHARS = 500
_TAIL_CHARS = 300


def truncate_for_noul(text: str, max_chars: int = _MAX_CHARS) -> str:
    """Truncate long articles to head + tail so closing exceptions survive."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    head = max(0, max_chars - _TAIL_CHARS)
    return text[:head] + "\n（中略）\n" + text[-_TAIL_CHARS:]


class JevLike(Protocol):
    async def system_one(self, *, state: Any, questions: dict, model: str | None = None) -> dict: ...


@dataclass
class ArticleRelevance:
    uid: str
    noul: float | None
    relevant: bool
    article: RetrievedArticle


def _noul_question(article: RetrievedArticle) -> dict:
    return {
        "type": "noul",
        "instructions": {
            "question": "Does `article` provide a legal basis that can answer `query`?",
            "article": {
                "citation": article.citation,
                "text": truncate_for_noul(article.text),
            },
        },
        "criteria": {
            "true": "The article states a rule, condition, or exception that answers the query.",
            "false": "The article is off-topic, only loosely related, or cannot support an answer.",
        },
    }


async def judge_articles(
    query: str,
    items: list[RetrievedArticle],
    jev: JevLike | None,
    *,
    min_noul: float = 0.5,
) -> list[ArticleRelevance]:
    if not items:
        return []
    if jev is None:
        return [ArticleRelevance(uid=it.uid, noul=None, relevant=True, article=it) for it in items]
    questions = {f"a{i}": _noul_question(it) for i, it in enumerate(items)}
    data = await jev.system_one(state={"query": query}, questions=questions)
    answers = data.get("answers") or {}
    out: list[ArticleRelevance] = []
    for i, it in enumerate(items):
        raw = answers.get(f"a{i}") or {}
        noul = float(raw["noul"]) if raw.get("noul") is not None else 0.0
        out.append(ArticleRelevance(uid=it.uid, noul=noul, relevant=noul >= min_noul, article=it))
    return out
