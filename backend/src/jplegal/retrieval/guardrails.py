"""Rule-based checks on a generated answer. No extra model call.

Citations in square brackets must match a retrieved article. A paragraph, item,
or caption suffix is still the same article; 第32条の2 is not 第32条. The
disclaimer is appended in code so it does not depend on the model.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

DISCLAIMER = "※本回答は法的助言ではありません。"

_CITE_RE = re.compile(r"\[([^\[\]\n]{2,120})\]")
_TAIL_RE = re.compile(r"^(?:第[0-9]+項)?(?:第[0-9]+号)?(?:\([^)]{0,40}\))?[。.]?$")


@dataclass
class GuardedAnswer:
    answer: str
    unsupported: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s)).strip()


def _cited_matches(cited: str, allowed: str) -> bool:
    c, a = _norm(cited), _norm(allowed)
    if not a:
        return False
    if c == a:
        return True
    if not c.startswith(a):
        return False
    return _TAIL_RE.fullmatch(c[len(a):].strip()) is not None


def guard_answer(answer: str, allowed_citations: list[str]) -> GuardedAnswer:
    body = answer.replace(DISCLAIMER, "").strip()
    unsupported: list[str] = []
    matched = 0
    seen: set[str] = set()
    for raw in _CITE_RE.findall(body):
        cite = raw.strip()
        if not cite or cite in seen:
            continue
        seen.add(cite)
        if any(_cited_matches(cite, allowed) for allowed in allowed_citations):
            matched += 1
        else:
            unsupported.append(cite)

    warnings: list[str] = []
    notes: list[str] = []
    if unsupported:
        warnings.append("unsupported_citation")
        listed = "、".join(f"[{c}]" for c in unsupported)
        notes.append(f"※次の引用は参照条文にありません: {listed}")
    if allowed_citations and matched == 0:
        warnings.append("missing_citation")
        notes.append("※回答に参照条文への引用がありません。根拠は上の参照条文で確認してください。")

    parts = [p for p in (body, *notes, DISCLAIMER) if p]
    return GuardedAnswer(answer="\n".join(parts), unsupported=unsupported, warnings=warnings)
