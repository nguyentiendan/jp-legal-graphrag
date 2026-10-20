"""Normalize kanji numerals / article numbers.

    kanji_to_int("三十二")          -> 32
    kanji_to_int("千二百三十四")     -> 1234
    article_key_from_title("第三十二条の二")  -> "32_2"
    display_article("32_2")         -> "第32条の2"
"""

from __future__ import annotations

import re
import unicodedata

_DIGITS = {"〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_UNITS = {"十": 10, "百": 100, "千": 1000}

KANJI_NUM = "〇零一二三四五六七八九十百千"
NUM_CLASS = f"[{KANJI_NUM}0-9０-９]+"


def kanji_to_int(s: str) -> int:
    s = unicodedata.normalize("NFKC", s.strip())
    if not s:
        raise ValueError("empty number")
    if s.isdigit():
        return int(s)
    total, current = 0, 0
    for ch in s:
        if ch in _DIGITS:
            current = current * 10 + _DIGITS[ch]
        elif ch in _UNITS:
            total += (current or 1) * _UNITS[ch]
            current = 0
        else:
            raise ValueError(f"not a kanji number: {s!r}")
    return total + current


_ARTICLE_RE = re.compile(rf"第({NUM_CLASS})条((?:の{NUM_CLASS})*)")


def article_key_from_title(title: str) -> str | None:
    """'第三十二条の二の三' -> '32_2_3'. Returns None on no match."""
    m = _ARTICLE_RE.search(title)
    if not m:
        return None
    parts = [str(kanji_to_int(m.group(1)))]
    for sub in re.findall(rf"の({NUM_CLASS})", m.group(2) or ""):
        parts.append(str(kanji_to_int(sub)))
    return "_".join(parts)


def display_article(article_key: str) -> str:
    """'32_2' -> '第32条の2' (for display / citation)."""
    if article_key.startswith("suppl"):
        return f"附則 {article_key}"
    if article_key.startswith("c"):
        return f"[{article_key}]"
    head, *rest = article_key.split("_")
    return f"第{head}条" + "".join(f"の{r}" for r in rest)


def clean_text(s: str) -> str:
    """Strip ASCII whitespace from XML indent (law text uses no meaningful ASCII spaces)."""
    return re.sub(r"[ \t\r\n]+", "", s).strip()
