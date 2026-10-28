"""Query rewriting: colloquial Japanese → statutory terms (grounded in backend/eval/*.jsonl)."""

import pytest

from jplegal.core.config import Settings
from jplegal.retrieval.pipeline import RetrievalOptions, Retriever
from jplegal.retrieval.query_rewrite import expand_query


def test_expands_overtime_pay_to_statutory_term():
    # eval q02: 「残業代の割増率…」 -> relevant articles phrase it as 割増賃金
    expanded = expand_query("残業代の割増率は何パーセント以上ですか？")
    assert "残業代" in expanded  # original kept
    assert "割増賃金" in expanded


def test_longer_form_wins_over_substring():
    expanded = expand_query("サービス残業をなくしたい")
    assert "時間外労働" in expanded
    assert "残業代" not in expanded


def test_expands_agreement_and_leave_terms():
    assert "年次有給休暇" in expand_query("有給は何日もらえる？")
    assert "解雇" in expand_query("クビにされた")
    assert "解雇" in expand_query("首切りは有効か")
    expanded = expand_query("36協定で定める事項は？")
    assert "時間外労働" in expanded and "休日労働" in expanded


def test_no_change_when_already_formal():
    q = "割増賃金の計算方法は？"
    assert expand_query(q) == q


def test_no_duplication_when_formal_term_present():
    expanded = expand_query("残業と時間外労働の上限は？")
    assert expanded.count("時間外労働") == 1


def test_expanded_query_overlaps_statutory_doc_sparse_vector(sparse_encoder):
    # Mechanism check: without expansion, colloquial 「残業代」 shares no token
    # with the statutory wording 「割増賃金」; with expansion it does.
    doc = sparse_encoder.encode_doc("時間外労働に対する割増賃金を支払う")
    plain = set(sparse_encoder.encode_query("残業代について").indices)
    expanded = set(sparse_encoder.encode_query(expand_query("残業代について")).indices)
    doc_tokens = set(doc.indices)
    assert not (plain & doc_tokens)
    assert expanded & doc_tokens


class _StubModels:
    def __init__(self):
        self.embedded: list[str] = []

    async def embed_query(self, text: str) -> list[float]:
        self.embedded.append(text)
        return [1.0, 0.0]


class _StubQdrant:
    async def has_sparse(self) -> bool:
        return False

    async def search(self, vector, limit, law_ids=None):
        return []


class _StubNeo4j:
    async def expand(self, seeds, limit=500):
        return []

    async def get_articles(self, uids):
        return {}


class _StubContainer:
    def __init__(self):
        self.settings = Settings()
        self.models = _StubModels()
        self.sparse = None
        self.qdrant = _StubQdrant()
        self.neo4j = _StubNeo4j()


@pytest.mark.asyncio
async def test_pipeline_embeds_expanded_query_but_reports_original():
    c = _StubContainer()
    res = await Retriever(c).retrieve(
        "残業代は何パーセントですか？", RetrievalOptions(use_graph=False, use_rerank=False))
    assert res.query == "残業代は何パーセントですか？"
    assert len(c.models.embedded) == 1
    assert "割増賃金" in c.models.embedded[0]


@pytest.mark.asyncio
async def test_pipeline_rewrite_can_be_disabled():
    c = _StubContainer()
    await Retriever(c).retrieve(
        "残業代は何パーセントですか？",
        RetrievalOptions(use_graph=False, use_rerank=False, use_rewrite=False))
    assert c.models.embedded[0] == "残業代は何パーセントですか？"
