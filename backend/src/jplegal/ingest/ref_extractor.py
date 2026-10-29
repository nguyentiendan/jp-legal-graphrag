"""Rule-based reference extraction from Japanese law text.

Supports:
  * 第◯条(の◯)… – same law or preceded by a law name: 労働契約法第十八条, 法第十五条, 同法第二条
  * 前条 / 前二条 / 次条 / 同条
  * Ranges: 第三十二条から第三十二条の五まで (expanded in article order within the same law)
  * 準用 → APPLIES_MUTATIS_MUTANDIS
  * 委任: 政令で定める / ◯◯省令で定める → DELEGATES_TO (to 施行令 / 施行規則)
  * Short-name definitions: 労働基準法（昭和二十二年法律第四十九号。以下「法」という。）
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from jplegal.core.models import Article, ParsedLaw, RawReference, Relation
from jplegal.ingest.normalize import NUM_CLASS, kanji_to_int

_SAME_NAMES = {"同法", "同令", "同規則", "同省令", "同政令"}
SELF_NAMES = {"この法律", "この政令", "この省令", "この規則", "この府令", "本法", "この命令"}
_LAW_SUFFIX = r"(?:法律|法|政令|令|省令|府令|規則)"

_REF_RE = re.compile(
    rf"(?P<abs>第(?P<n>{NUM_CLASS})条(?P<sub>(?:の{NUM_CLASS})*))"
    rf"|(?P<rel>[前次同])(?P<cnt>[二三四五六七八九]?)条"
)
_NAME_BEFORE_RE = re.compile(rf"(?P<name>[^\s、。「」（）()　]*?{_LAW_SUFFIX})$")
_ALIAS_RE = re.compile(
    rf"(?P<name>[^\s、。「」（）()　]+?{_LAW_SUFFIX})（(?:[^（）]*?。)?以下「(?P<alias>[^」]{{1,20}})」という。?）"
)
_PARTICLE_SPLIT_RE = re.compile(
    rf"(?:第{NUM_CLASS}(?:条|項|号)(?:の{NUM_CLASS})*|に規定する|の規定|準用する|適用する|規定する|は、?|が、?|を|において|により|による"
    r"|について|に基づく|、|　)"
)
_LEADING_JUNK_RE = re.compile(r"^(?:及び|並びに|又は|若しくは|の|改正する|改正後の|改正前の)+")
_NAME_CHAR_RE = re.compile(r"[一-龥々ァ-ヶー]")
_QUOTE_RE = re.compile(r"「[^「」]*」")
_SUB_REF_RE = re.compile(rf"(?:第{NUM_CLASS}[項号]|ただし書|本文|前段|後段|各号|(?:の{NUM_CLASS}))")
_CONNECTORS = {"", "から", "及び", "又は", "並びに", "若しくは", "、", "乃至", "まで、", "まで及び", "まで又は"}
_DELEGATION_RE = re.compile(r"(政令|[一-龥]{0,10}省令|府令|命令)で定める")
_PARA_AFTER_RE = re.compile(rf"^第(?P<p>{NUM_CLASS})項")
_ITEM_AFTER_RE = re.compile(rf"^第(?P<i>{NUM_CLASS})号")


@dataclass
class _Target:
    law_name: str | None  # None = same law
    key: str


def _key(n: str, sub: str) -> str:
    parts = [str(kanji_to_int(n))]
    parts += [str(kanji_to_int(x)) for x in re.findall(rf"の({NUM_CLASS})", sub or "")]
    return "_".join(parts)


def _strip_trailing_paren(s: str) -> str:
    """Drop a trailing （…） group (may nest 1 level)."""
    while s.endswith("）"):
        depth = 0
        for i in range(len(s) - 1, -1, -1):
            ch = s[i]
            if ch == "）":
                depth += 1
            elif ch == "（":
                depth -= 1
                if depth == 0:
                    s = s[:i]
                    break
        else:
            return s
    return s


def split_sentences(text: str) -> list[str]:
    """Split sentences at 「。」 outside （） and 「」."""
    out, buf, depth = [], [], 0
    for ch in text:
        buf.append(ch)
        if ch in "（「(":
            depth += 1
        elif ch in "）」)":
            depth = max(0, depth - 1)
        elif ch == "。" and depth == 0:
            out.append("".join(buf))
            buf = []
    if buf:
        out.append("".join(buf))
    return out


def trim_law_name(raw: str) -> str:
    """'この規則は労働基準法' -> '労働基準法'."""
    pieces = [p for p in _PARTICLE_SPLIT_RE.split(raw) if p]
    name = pieces[-1] if pieces else raw
    return _LEADING_JUNK_RE.sub("", name) or name


def parent_title(title: str) -> str | None:
    for suf in ("施行令", "施行規則"):
        if title.endswith(suf) and len(title) > len(suf):
            return title[: -len(suf)]
    return None


def extract_aliases(parsed: ParsedLaw) -> dict[str, str]:
    title = parsed.meta.title
    aliases: dict[str, str] = {}
    parent = parent_title(title)
    if parent:  # defaults for 施行令 / 施行規則
        aliases["法"] = parent
        aliases["令"] = f"{parent}施行令"
    defined: set[str] = set()  # aliases defined in the text (take precedence over defaults)
    for art in parsed.articles:
        if art.is_suppl:
            continue
        for m in _ALIAS_RE.finditer(art.text):
            name = trim_law_name(m.group("name"))
            alias = m.group("alias")
            if len(name) >= 2 and alias not in defined:
                aliases[alias] = name
                defined.add(alias)
    return aliases


class ReferenceExtractor:
    def __init__(self, parsed: ParsedLaw, aliases: dict[str, str] | None = None):
        self.parsed = parsed
        self.title = parsed.meta.title
        self.aliases = aliases if aliases is not None else extract_aliases(parsed)
        main = [a for a in parsed.articles if not a.is_suppl]
        self._main_keys = [a.article_key for a in main]
        self._index = {k: i for i, k in enumerate(self._main_keys)}

    # ---------- helpers ----------
    def _law_before(self, before: str, last_law: str | None) -> str | None:
        """Determine the law named right before 第◯条. None = same law."""
        stripped = _strip_trailing_paren(before)
        # 1) short name / この法律 / 同法 – only when the preceding char is not part of a law name
        specials = list(SELF_NAMES) + list(_SAME_NAMES) + list(self.aliases)
        for name in sorted(specials, key=len, reverse=True):
            if stripped.endswith(name):
                pre = stripped[: -len(name)]
                if pre and _NAME_CHAR_RE.match(pre[-1]):
                    continue
                if name in SELF_NAMES:
                    return None
                if name in _SAME_NAMES:
                    return last_law
                target = self.aliases[name]
                return None if target == self.title else target
        # 2) full law name
        nm = _NAME_BEFORE_RE.search(stripped)
        if not nm:
            return None
        name = trim_law_name(nm.group("name"))
        if len(name) < 2 or name == self.title or name in SELF_NAMES:
            return None
        if name in self.aliases:
            target = self.aliases[name]
            return None if target == self.title else target
        if not _NAME_CHAR_RE.match(name[0]) and len(name) < 3:
            return None
        return name

    def _expand_range(self, a: str, b: str) -> list[str]:
        ia, ib = self._index.get(a), self._index.get(b)
        if ia is None or ib is None or ib < ia or ib - ia > 30:
            return [a, b]
        return self._main_keys[ia : ib + 1]

    # ---------- main ----------
    def extract_article(self, art: Article) -> list[RawReference]:
        refs: dict[tuple, RawReference] = {}
        law_id = art.law_id
        idx = self._index.get(art.article_key)
        last_law: str | None = None  # cho 同法
        base_title = parent_title(self.title) or self.title

        def add(t: _Target, relation: Relation, span: str, para: int | None = None,
                item: str | None = None) -> None:
            if t.law_name is None and t.key == art.article_key:
                return
            k = (t.law_name, t.key, relation)
            if k not in refs:
                refs[k] = RawReference(src_uid=art.uid, src_law_id=law_id, relation=relation, raw_span=span,
                                       target_law_name=t.law_name, target_article_key=t.key,
                                       target_para=para, target_item=item)

        for para in art.paragraphs:
            for sentence in split_sentences(para.text):
                if not sentence:
                    continue
                relation = Relation.APPLIES_MUTATIS_MUTANDIS if "準用" in sentence else Relation.REFERS_TO
                prev_end = -1
                prev_target: _Target | None = None
                last_article_target: _Target | None = None
                quoted = [(q.start(), q.end()) for q in _QUOTE_RE.finditer(sentence)]
                for m in _REF_RE.finditer(sentence):
                    if any(a <= m.start() < b for a, b in quoted):
                        continue  # 読み替え「…」 – not a real reference
                    span = sentence[max(0, m.start() - 20) : m.end() + 10]
                    if m.group("rel"):
                        kind, cnt = m.group("rel"), m.group("cnt")
                        n = kanji_to_int(cnt) if cnt else 1
                        targets: list[_Target] = []
                        if kind == "前" and idx is not None:
                            targets = [_Target(None, self._main_keys[i]) for i in range(max(0, idx - n), idx)]
                        elif kind == "次" and idx is not None:
                            targets = [_Target(None, self._main_keys[i])
                                       for i in range(idx + 1, min(len(self._main_keys), idx + 1 + n))]
                        elif kind == "同" and last_article_target is not None:
                            targets = [last_article_target]
                        for t in targets:
                            add(t, relation, span)
                        if targets:
                            prev_target, prev_end = targets[-1], m.end()
                        continue

                    key = _key(m.group("n"), m.group("sub"))
                    before = sentence[: m.start()]
                    gap = _SUB_REF_RE.sub("", sentence[prev_end : m.start()]) if prev_end >= 0 else None
                    law_name: str | None
                    is_range = False
                    if prev_target is not None and gap in _CONNECTORS:
                        law_name = prev_target.law_name
                        is_range = gap == "から"
                    else:
                        law_name = self._law_before(before, last_law)
                    if law_name is not None:
                        last_law = law_name
                    target = _Target(law_name, key)
                    if is_range and law_name is None and prev_target is not None:
                        for k in self._expand_range(prev_target.key, key):
                            add(_Target(None, k), relation, span)
                    else:
                        tail = sentence[m.end() :]
                        pm = _PARA_AFTER_RE.match(tail)
                        para = kanji_to_int(pm.group("p")) if pm else None
                        rest = tail[pm.end() :] if pm else tail
                        im = _ITEM_AFTER_RE.match(rest)
                        item = im.group("i") if im else None
                        add(target, relation, span, para=para, item=item)
                    prev_target, prev_end, last_article_target = target, m.end(), target

                # 委任
                for dm in _DELEGATION_RE.finditer(sentence):
                    kind = dm.group(1)
                    law_type = self.parsed.meta.law_type
                    if kind == "政令":
                        if law_type == "CabinetOrder":
                            continue
                        suffix = "施行令"
                    else:
                        if law_type == "MinisterialOrdinance":
                            continue
                        suffix = "施行規則"
                    tname = f"{base_title}{suffix}"
                    if tname == self.title:
                        continue
                    k = (tname, None, Relation.DELEGATES_TO)
                    if k not in refs:
                        refs[k] = RawReference(src_uid=art.uid, src_law_id=law_id, relation=Relation.DELEGATES_TO,
                                               raw_span=sentence[max(0, dm.start() - 30) : dm.end() + 5],
                                               target_law_name=tname, target_article_key=None,
                                               target_law_suffix=suffix)
        return list(refs.values())

    def extract_all(self) -> list[RawReference]:
        out: list[RawReference] = []
        for art in self.parsed.articles:
            out.extend(self.extract_article(art))
        return out


def extract_references(parsed: ParsedLaw) -> tuple[dict[str, str], list[RawReference]]:
    aliases = extract_aliases(parsed)
    parsed.aliases = aliases
    return aliases, ReferenceExtractor(parsed, aliases).extract_all()
