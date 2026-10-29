"""Extract 定義語 from statute text: 「平均賃金」とは、…をいう."""

from __future__ import annotations

import re

from jplegal.core.models import ParsedLaw

_TERM_RE = re.compile(
    r"「(?P<name>[^」]{2,40})」とは[、,]?(?P<body>.+?)をいう"
)


def extract_terms(parsed: ParsedLaw) -> list[dict]:
    """Return [{name, uid, law_id, article_key, body}] for DEFINES edges."""
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for art in parsed.articles:
        if art.is_suppl:
            continue
        for m in _TERM_RE.finditer(art.text):
            name = m.group("name").strip()
            key = (name, art.uid)
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "name": name,
                "uid": art.uid,
                "law_id": art.law_id,
                "article_key": art.article_key,
                "body": m.group("body")[:400],
            })
    return out
