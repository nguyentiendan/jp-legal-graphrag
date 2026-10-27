import pytest

from jplegal.retrieval.intent import QueryIntent, classify_intent, direct_answer


class FakeJev:
    def __init__(self, answers: dict):
        self.answers = answers
        self.calls: list[dict] = []

    async def system_one(self, *, state, questions, model=None):
        self.calls.append({"state": state, "questions": questions, "model": model})
        return {"answers": self.answers}


def _choice(label: str, confidence: float = 0.9) -> dict:
    rest = (1.0 - confidence) / 2
    probs = {"greeting": rest, "rag_query": rest, "out_of_scope": rest}
    probs[label] = confidence
    return {
        "intent": {
            "type": "choice",
            "choice": label,
            "confidence": confidence,
            "probabilities": probs,
        }
    }


@pytest.mark.asyncio
async def test_greeting_choice_skips_retrieval():
    jev = FakeJev(_choice("greeting", 0.94))
    classified = await classify_intent("Hello, How are you", jev)
    assert classified.intent is QueryIntent.GREETING
    assert classified.probabilities["greeting"] == pytest.approx(0.94)
    q = jev.calls[0]["questions"]["intent"]
    assert q["type"] == "choice"
    assert set(q["criteria"]) == {"greeting", "rag_query", "out_of_scope"}
    answer = direct_answer(classified.intent)
    assert answer is not None
    assert "労働法令" in answer
    assert "引用がありません" not in answer


@pytest.mark.asyncio
async def test_out_of_scope_choice_skips_retrieval():
    jev = FakeJev(_choice("out_of_scope", 0.91))
    classified = await classify_intent("What is RAG", jev)
    assert classified.intent is QueryIntent.OUT_OF_SCOPE
    assert direct_answer(classified.intent) is not None


@pytest.mark.asyncio
async def test_legal_choice_goes_to_rag():
    jev = FakeJev(_choice("rag_query", 0.88))
    classified = await classify_intent("残業代の割増率は何パーセントですか", jev)
    assert classified.intent is QueryIntent.RAG_QUERY
    assert direct_answer(classified.intent) is None


@pytest.mark.asyncio
async def test_low_confidence_greeting_falls_through_to_rag():
    jev = FakeJev(_choice("greeting", 0.31))
    classified = await classify_intent("hey 残業は？", jev, min_confidence=0.5)
    assert classified.intent is QueryIntent.RAG_QUERY


@pytest.mark.asyncio
async def test_missing_jev_fails_open_to_rag():
    classified = await classify_intent("Hello", None)
    assert classified.intent is QueryIntent.RAG_QUERY
    assert classified.fallback is True
