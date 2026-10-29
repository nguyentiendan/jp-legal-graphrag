import pytest

from jplegal.ingest.normalize import article_key_from_title, display_article, kanji_to_int


@pytest.mark.parametrize(
    "s,n",
    [("一", 1), ("十", 10), ("十一", 11), ("二十", 20), ("三十二", 32), ("百", 100), ("百二十", 120),
     ("百五", 105), ("千二百三十四", 1234), ("千", 1000), ("12", 12), ("１２", 12)],
)
def test_kanji_to_int(s, n):
    assert kanji_to_int(s) == n


@pytest.mark.parametrize(
    "title,key",
    [("第一条", "1"), ("第三十二条", "32"), ("第三十二条の二", "32_2"), ("第三十八条の四の二", "38_4_2"),
     ("第百十五条", "115"), ("第１２条", "12")],
)
def test_article_key(title, key):
    assert article_key_from_title(title) == key


def test_display():
    assert display_article("32_2") == "第32条の2"
    assert display_article("32", para_num=1, proviso=True) == "第32条第1項ただし書"
    assert display_article("1") == "第1条"


def test_display_special_keys():
    # 本則 (short law whose MainProvision holds only Paragraphs) – see egov_xml.parse_egov_xml
    assert display_article("main") == "本則"
    # 附則 articles – see egov_xml prefix f"suppl{si}_"
    assert display_article("suppl0_1") == "附則 第1条"
    assert display_article("suppl2_3") == "附則 第3条"
    assert display_article("suppl0_0") == "附則"
    # upload pseudo-articles without 条 structure – see text_doc.parse_text_document
    assert display_article("c1") == "(1)"
    # duplicate article numbers in uploads (e.g. 附則 restating 第32条)
    assert display_article("32-1") == "第32条(2)"
    assert display_article("32_2-1") == "第32条の2(2)"
