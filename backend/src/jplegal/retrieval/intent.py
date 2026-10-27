"""Task 1: intent classification with Jev Choice, before retrieval.

greeting / out_of_scope → fixed reply. rag_query → existing RAG pipeline.
A missing Jev client fails open to rag_query so legal questions are never dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from jplegal.retrieval.guardrails import guard_answer

_GREETING_REPLY = "こんにちは。日本の労働法令についてご質問ください。"
_SCOPE_REPLY = "このシステムは日本の労働法令に関する質問にだけ回答します。法令について質問してください。"

INTENT_QUESTION = {
    "type": "choice",
    "instructions": "Which intent matches what the user asks for in `message`?",
    "criteria": {
        "greeting": (
            "A greeting, thanks, or small talk with no request about Japanese law "
            "or employment."
        ),
        "rag_query": (
            "A question about Japanese labour law, employment, wages, working hours, "
            "leave, dismissal, safety, or a statute. Includes a greeting followed by "
            "such a question."
        ),
        "out_of_scope": (
            "Not a greeting, and not about Japanese law or employment "
            "(for example general tech questions or file-upload requests)."
        ),
    },
}


class QueryIntent(StrEnum):
    GREETING = "greeting"
    RAG_QUERY = "rag_query"
    OUT_OF_SCOPE = "out_of_scope"


class JevLike(Protocol):
    async def system_one(self, *, state: Any, questions: dict, model: str | None = None) -> dict: ...


@dataclass
class IntentResult:
    intent: QueryIntent
    confidence: float | None = None
    probabilities: dict[str, float] = field(default_factory=dict)
    fallback: bool = False


async def classify_intent(
    query: str,
    jev: JevLike | None,
    *,
    min_confidence: float = 0.5,
) -> IntentResult:
    if jev is None:
        return IntentResult(intent=QueryIntent.RAG_QUERY, fallback=True)
    data = await jev.system_one(state={"message": query}, questions={"intent": INTENT_QUESTION})
    ans = data["answers"]["intent"]
    raw = str(ans.get("choice") or QueryIntent.RAG_QUERY)
    try:
        chosen = QueryIntent(raw)
    except ValueError:
        chosen = QueryIntent.RAG_QUERY
    confidence = float(ans.get("confidence") or 0.0)
    probs = {k: float(v) for k, v in (ans.get("probabilities") or {}).items()}
    if chosen is not QueryIntent.RAG_QUERY and confidence < min_confidence:
        chosen = QueryIntent.RAG_QUERY
    return IntentResult(intent=chosen, confidence=confidence, probabilities=probs)


def direct_answer(intent: QueryIntent) -> str | None:
    if intent is QueryIntent.RAG_QUERY:
        return None
    text = _GREETING_REPLY if intent is QueryIntent.GREETING else _SCOPE_REPLY
    return guard_answer(text, []).answer
