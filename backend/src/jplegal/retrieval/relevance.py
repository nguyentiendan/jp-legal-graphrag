"""Task 2: document relevance with Jev Noul, after retrieval.

Independent of intent. One Noul per retrieved article in a single System One call.
Does not call the Ruri reranker.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from jplegal.retrieval.pipeline import RetrievedArticle

_MAX_CHARS = 800


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
                "text": article.text[:_MAX_CHARS],
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
