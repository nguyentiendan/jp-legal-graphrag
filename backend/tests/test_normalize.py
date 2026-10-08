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
    assert display_article("1") == "第1条"
