import pytest

from jplegal.retrieval.pipeline import RetrievedArticle
from jplegal.retrieval.relevance import judge_articles


class FakeJev:
    def __init__(self, answers: dict):
        self.answers = answers
        self.calls: list[dict] = []

    async def system_one(self, *, state, questions, model=None):
        self.calls.append({"state": state, "questions": questions, "model": model})
        return {"answers": self.answers}


def _article(uid: str, citation: str, text: str) -> RetrievedArticle:
    law_id, key = uid.split("#")
    return RetrievedArticle(
        uid=uid,
        law_id=law_id,
        law_title=citation.split(" ")[0],
        article_key=key,
        title="",
        caption="",
        path="",
        text=text,
    )


@pytest.mark.asyncio
async def test_relevance_is_a_noul_per_article_not_an_intent_choice():
    items = [
        _article("L#39", "労働基準法 第39条", "年次有給休暇"),
        _article("L#32", "労働基準法 第32条", "労働時間"),
    ]
    jev = FakeJev({"a0": {"type": "noul", "noul": 0.12}, "a1": {"type": "noul", "noul": 0.93}})
    judged = await judge_articles("残業代の割増率は？", items, jev, min_noul=0.5)
    q = jev.calls[0]["questions"]
    assert all(v["type"] == "noul" for v in q.values())
    assert "intent" not in q
    assert jev.calls[0]["state"]["query"] == "残業代の割増率は？"
    assert judged[0].uid == "L#39" and judged[0].relevant is False
    assert judged[1].uid == "L#32" and judged[1].relevant is True
    assert [it.uid for it in judged if it.relevant] == ["L#32"]


@pytest.mark.asyncio
async def test_relevance_without_jev_keeps_every_article():
    items = [_article("L#32", "労働基準法 第32条", "労働時間")]
    judged = await judge_articles("残業は？", items, None)
    assert judged[0].relevant is True
    assert judged[0].noul is None
