"""BM25 / Sudachi: chuẩn hoá số, tách từ đa độ mịn, trọng số BM25."""

from jplegal.retrieval.sparse import BM25Encoder, normalize_for_tokenize, token_id


def test_normalize_kanji_numbers():
    assert normalize_for_tokenize("法第三十七条第一項") == "法第37条第1項"
    assert normalize_for_tokenize("一日八時間、一週間について四十時間") == "1日8時間、1週間について40時間"
    assert normalize_for_tokenize("一般の労働者") == "一般の労働者"  # từ thường không bị đổi
    assert normalize_for_tokenize("２割５分") == "2割5分"  # NFKC


def test_tokenize_multigranular(sparse_encoder):
    toks = sparse_encoder.tok.tokenize("割増賃金の計算から除外される手当")
    assert "割増賃金" in toks and "賃金" in toks  # từ ghép (C) + từ đơn (A)
    assert "の" not in toks and "から" not in toks  # bỏ trợ từ
    assert "三六協定" in sparse_encoder.tok.tokenize("36協定の届出")  # normalized_form


def test_article_number_matches_kanji(sparse_encoder):
    q = set(sparse_encoder.encode_query("37条").indices)
    d = set(sparse_encoder.encode_doc("法第三十七条第一項の規定による割増賃金").indices)
    assert token_id("37") in q & d


def test_bm25_weights(sparse_encoder: BM25Encoder):
    short = sparse_encoder.encode_doc("賃金 賃金")
    long = sparse_encoder.encode_doc("賃金 賃金 " + "労働時間 休日 休憩 " * 50)
    w = {i: v for i, v in zip(short.indices, short.values)}[token_id("賃金")]
    w_long = {i: v for i, v in zip(long.indices, long.values)}[token_id("賃金")]
    assert 0 < w_long < w  # văn bản dài → trọng số tf thấp hơn (chuẩn hoá độ dài)
    assert max(short.values) <= sparse_encoder.k1 + 1  # tf bão hoà
    q = sparse_encoder.encode_query("賃金 賃金 休日")
    assert q.values == [1.0] * len(q.indices) and len(set(q.indices)) == len(q.indices)
    assert not sparse_encoder.encode_query("の、は")
