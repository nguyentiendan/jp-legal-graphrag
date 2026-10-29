from pathlib import Path

from jplegal.core.models import Article, LawMeta, Paragraph, ParsedLaw, Relation
from jplegal.ingest.chunker import build_chunks
from jplegal.ingest.linker import LawRegistry
from jplegal.ingest.parsers.egov_xml import ids_from_filename, parse_egov_xml
from jplegal.ingest.parsers.text_doc import parse_text_document
from jplegal.ingest.ref_extractor import ReferenceExtractor, extract_aliases, extract_references, parent_title
from jplegal.ingest.terms import extract_terms
from jplegal.stores.neo4j_store import keep_incoming

FIX = Path(__file__).parent / "fixtures" / "419AC0000000128_roudoukeiyaku.xml"


def _law(title: str, arts: list[tuple[str, str]], law_type: str = "Act", law_id: str = "L1") -> ParsedLaw:
    articles = [
        Article(law_id=law_id, article_key=k, title=f"第{k}条", paragraphs=[Paragraph(1, "", t)], order=i)
        for i, (k, t) in enumerate(arts)
    ]
    return ParsedLaw(meta=LawMeta(law_id=law_id, title=title, law_type=law_type), articles=articles)


def test_parse_roudoukeiyaku():
    pl = parse_egov_xml(FIX.read_bytes(), law_id="419AC0000000128")
    assert pl.meta.title == "労働契約法"
    assert pl.meta.abbrev == "労契法"
    keys = [a.article_key for a in pl.articles]
    assert keys[0] == "1" and "18" in keys and "16" in keys
    a16 = next(a for a in pl.articles if a.article_key == "16")
    assert a16.caption == "（解雇）"
    assert "客観的に合理的な理由を欠き" in a16.text
    assert a16.path and a16.path[0].startswith("第三章")


def test_refs_roudoukeiyaku():
    pl = parse_egov_xml(FIX.read_bytes(), law_id="419AC0000000128")
    _, refs = extract_references(pl)
    ext = {(r.target_law_name, r.target_article_key) for r in refs if r.target_law_name}
    assert ("労働基準法", "89") in ext
    assert any(r.relation == Relation.DELEGATES_TO and r.target_law_name == "労働契約法施行規則" for r in refs)


def test_relative_and_range_refs():
    pl = _law("テスト法", [
        ("1", "目的を定める。"),
        ("2", "前条の規定は適用する。"),
        ("3", "第一条から第二条までの規定にかかわらず、次条に定める。"),
        ("4", "前二条の規定は、この場合について準用する。"),
    ])
    refs = ReferenceExtractor(pl).extract_all()
    by_src = {}
    for r in refs:
        by_src.setdefault(r.src_uid, set()).add((r.target_article_key, r.relation))
    assert ("1", Relation.REFERS_TO) in by_src["L1#2"]
    assert {("1", Relation.REFERS_TO), ("2", Relation.REFERS_TO), ("4", Relation.REFERS_TO)} <= by_src["L1#3"]
    assert {("2", Relation.APPLIES_MUTATIS_MUTANDIS), ("3", Relation.APPLIES_MUTATIS_MUTANDIS)} <= by_src["L1#4"]


def test_external_and_alias_refs():
    pl = _law("労働基準法施行規則", [
        ("1", "労働基準法（昭和二十二年法律第四十九号。以下「法」という。）第十五条第一項の規定による。"),
        ("2", "使用者は、法第三十六条第一項の協定をする。労働契約法（平成十九年法律第百二十八号）第十八条を参照。"),
        ("3", "同法第十九条の規定は、法第三十二条及び第三十三条について準用する。"),
        ("4", "第七条中「第十二条」とあるのは「船員法第百条」とする。"),
    ], law_type="MinisterialOrdinance")
    aliases = extract_aliases(pl)
    assert aliases["法"] == "労働基準法"
    refs = ReferenceExtractor(pl, aliases).extract_all()
    got = {(r.src_uid, r.target_law_name, r.target_article_key, r.relation) for r in refs}
    assert ("L1#1", "労働基準法", "15", Relation.REFERS_TO) in got
    assert ("L1#2", "労働基準法", "36", Relation.REFERS_TO) in got
    assert ("L1#2", "労働契約法", "18", Relation.REFERS_TO) in got
    # 法第三十二条及び第三十三条 → both belong to 労働基準法
    assert ("L1#3", "労働基準法", "33", Relation.APPLIES_MUTATIS_MUTANDIS) in got
    # references inside 「」 (読み替え) are skipped
    assert not any(r.src_uid == "L1#4" and r.target_article_key == "12" for r in refs)


def test_delegation():
    pl = _law("テスト法", [("1", "必要な事項は、厚生労働省令で定める。"), ("2", "率は政令で定める。")])
    refs = ReferenceExtractor(pl).extract_all()
    d = {(r.src_uid, r.target_law_name) for r in refs if r.relation == Relation.DELEGATES_TO}
    assert ("L1#1", "テスト法施行規則") in d and ("L1#2", "テスト法施行令") in d


def test_parent_title():
    assert parent_title("労働基準法施行規則") == "労働基準法"
    assert parent_title("労働基準法施行令") == "労働基準法"
    assert parent_title("労働基準法") is None


def test_registry_resolve():
    class R:
        def __init__(self, law_id, title, abbrev=""):
            self.law_id, self.title, self.abbrev = law_id, title, abbrev

    reg = LawRegistry([R("A", "労働基準法", "労基法"), R("B", "職業能力開発促進法施行規則"),
                       R("C", "育児休業、介護休業等育児又は家族介護を行う労働者の福祉に関する法律")])
    assert reg.resolve("労働基準法") == "A"
    assert reg.resolve("労基法") == "A"
    assert reg.resolve("受ける職業訓練の訓練課程に応じ職業能力開発促進法施行規則") == "B"
    assert reg.resolve("行う労働者の福祉に関する法律") == "C"
    assert reg.resolve("存在しない法") is None


def test_chunker_split_long():
    long = "あ" * 1000 + "。"
    pl = _law("テスト法", [("1", long * 4)])
    chunks = build_chunks(pl, max_chars=1500)
    assert len(chunks) >= 3
    assert all(c.article_uid == "L1#1" for c in chunks)
    assert chunks[0].embed_text.startswith("テスト法 第1条")
    assert chunks[0].para_num == 1


def test_text_document():
    text = "就業規則\n\n第一章　総則\n（目的）\n第一条　この規則は、従業員の労働条件を定める。\n２　この規則に定めのない事項は労働基準法による。\n（適用範囲）\n第二条　この規則は、全従業員に適用する。\n"
    pl = parse_text_document(text, law_id="upload-x", title="就業規則")
    assert [a.article_key for a in pl.articles] == ["1", "2"]
    a1 = pl.articles[0]
    assert a1.caption == "（目的）" and len(a1.paragraphs) == 2 and a1.path == ["第一章　総則"]


def test_chunker_keeps_paragraphs_separate():
    pl = _law("テスト法", [("1", "第一項の本文。")])
    pl.articles[0].paragraphs.append(Paragraph(2, "２", "第二項ただし書。"))
    chunks = build_chunks(pl)
    assert [c.para_num for c in chunks] == [1, 2]
    assert chunks[1].proviso


def test_extracts_paragraph_from_reference():
    pl = _law("テスト法", [("1", "第十二条第一項の規定による。")])
    refs = ReferenceExtractor(pl).extract_all()
    r = next(x for x in refs if x.target_article_key == "12")
    assert r.target_para == 1


def test_term_pattern_heikin_chingin():
    pl = _law("労働基準法", [("12", "この法律で「平均賃金」とは、これを算定すべき事由の発生した日以前三箇月間に支払われた賃金の総額をいう。")])
    terms = extract_terms(pl)
    assert terms and terms[0]["name"] == "平均賃金"
    assert terms[0]["article_key"] == "12"


def test_drop_incoming_refers_to_hubs():
    assert keep_incoming("REFERS_TO", True, 99, 8)
    assert keep_incoming("REFERS_TO", False, 3, 8)
    assert not keep_incoming("REFERS_TO", False, 20, 8)
    assert keep_incoming("APPLIES_MUTATIS_MUTANDIS", False, 20, 8)


def test_ids_from_filename():
    assert ids_from_filename("322AC0000000049_20260717_508AC0000000060.xml") == (
        "322AC0000000049", "322AC0000000049_20260717_508AC0000000060")
    assert ids_from_filename("foo.xml") == (None, "")
