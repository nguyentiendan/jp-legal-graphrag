"""Rule-based checks on a generated answer. No extra model call.

Citations in square brackets must match a retrieved article. Caption / 号 tails
are the same article. Citing 第N項 is allowed only when that 項 is in the
retrieved chunk (para_num or body). 第32条の2 is not 第32条.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from jplegal.retrieval.pipeline import RetrievedArticle

DISCLAIMER = "※本回答は法的助言ではありません。"

_CITE_RE = re.compile(r"\[([^\[\]\n]{2,120})\]")
_CORE_RE = re.compile(r"^(.+?第[0-9]+条(?:の[0-9]+)*)")
_PARA_RE = re.compile(r"第([0-9]+)項")
_TAIL_RE = re.compile(r"^(?:第[0-9]+号)?(?:ただし書)?(?:\([^)]{0,40}\))?[。.]?$")


@dataclass
class GuardedAnswer:
    answer: str
    unsupported: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s)).strip()


def _core(s: str) -> str:
    n = _norm(s)
    m = _CORE_RE.match(n)
    return m.group(1) if m else n


def _para_in_text(text: str, n: int) -> bool:
    t = _norm(text)
    if f"第{n}項" in t:
        return True
    # numbered 項 often starts with ２　 (fullwidth)
    labels = {1: ("1", "１"), 2: ("2", "２"), 3: ("3", "３"), 4: ("4", "４"), 5: ("5", "５")}
    for lab in labels.get(n, (str(n),)):
        if t.startswith(lab) or f"\n{lab}" in t:
            return True
    return False


def _cited_matches(cited: str, allowed: str | RetrievedArticle) -> bool:
    item = allowed if isinstance(allowed, RetrievedArticle) else None
    allowed_cite = item.citation if item else str(allowed)
    c, a = _norm(cited), _norm(allowed_cite)
    if not a:
        return False
    cc, ac = _core(c), _core(a)
    if cc != ac:
        return False
    pn = _PARA_RE.search(c)
    if pn is None:
        rest = c[len(cc):].strip()
        return _TAIL_RE.fullmatch(rest) is not None
    n = int(pn.group(1))
    if item is None:
        return False
    if item.para_num is not None and item.para_num == n:
        return True
    return _para_in_text(item.text, n)


def guard_answer(answer: str, allowed: list[str] | list[RetrievedArticle]) -> GuardedAnswer:
    body = answer.replace(DISCLAIMER, "").strip()
    unsupported: list[str] = []
    matched = 0
    seen: set[str] = set()
    for raw in _CITE_RE.findall(body):
        cite = raw.strip()
        if not cite or cite in seen:
            continue
        seen.add(cite)
        if any(_cited_matches(cite, allowed_item) for allowed_item in allowed):
            matched += 1
        else:
            unsupported.append(cite)

    warnings: list[str] = []
    notes: list[str] = []
    if unsupported:
        warnings.append("unsupported_citation")
        listed = "、".join(f"[{c}]" for c in unsupported)
        notes.append(f"※次の引用は参照条文にありません: {listed}")
    if allowed and matched == 0:
        warnings.append("missing_citation")
        notes.append("※回答に参照条文への引用がありません。根拠は上の参照条文で確認してください。")

    parts = [p for p in (body, *notes, DISCLAIMER) if p]
    return GuardedAnswer(answer="\n".join(parts), unsupported=unsupported, warnings=warnings)
