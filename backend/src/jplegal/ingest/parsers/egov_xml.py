"""Parser for e-Gov 法令標準XML (API v2 / XML一括ダウンロード).

Main structure:
    Law > LawBody > MainProvision > (Part > Chapter > Section > Subsection > Division)* > Article
    Article > ArticleCaption, ArticleTitle, Paragraph > ParagraphNum, ParagraphSentence > Sentence,
                                                    Item > ItemTitle, ItemSentence, Subitem1 ...
    LawBody > SupplProvision (附則)
"""

from __future__ import annotations

import re
from pathlib import Path

from lxml import etree

from jplegal.core.models import Article, LawMeta, Paragraph, ParsedLaw
from jplegal.ingest.normalize import clean_text

_CONTAINER_TITLES = {
    "Part": "PartTitle",
    "Chapter": "ChapterTitle",
    "Section": "SectionTitle",
    "Subsection": "SubsectionTitle",
    "Division": "DivisionTitle",
}
_FULLWIDTH = str.maketrans("0123456789", "０１２３４５６７８９")
_ERA = {"Meiji": "明治", "Taisho": "大正", "Showa": "昭和", "Heisei": "平成", "Reiwa": "令和"}


def _text(el: etree._Element | None) -> str:
    """itertext but skip furigana readings (<Rt>)."""
    if el is None:
        return ""
    parts: list[str] = []

    def rec(n: etree._Element) -> None:
        if not isinstance(n.tag, str) or n.tag == "Rt":
            return
        if n.text:
            parts.append(n.text)
        for c in n:
            rec(c)
            if c.tail:
                parts.append(c.tail)

    rec(el)
    return clean_text("".join(parts))


def _sentences(el: etree._Element | None) -> str:
    """Join <Sentence>/<Column> within one block (ParagraphSentence / ItemSentence)."""
    if el is None:
        return ""
    cols = el.findall("Column")
    if cols:
        return "　".join(_text(c) for c in cols)
    return _text(el)


def _item_text(item: etree._Element, depth: int = 0) -> list[str]:
    title_tag = "ItemTitle" if item.tag == "Item" else f"{item.tag}Title"
    sent_tag = "ItemSentence" if item.tag == "Item" else f"{item.tag}Sentence"
    title = _text(item.find(title_tag))
    sent = _sentences(item.find(sent_tag))
    lines = [("　" * depth) + f"{title}　{sent}".strip()]
    for child in item:
        if child.tag.startswith("Subitem"):
            lines.extend(_item_text(child, depth + 1))
    return lines


def _paragraph(p: etree._Element, idx: int) -> Paragraph:
    num_attr = p.get("Num") or str(idx)
    try:
        num = int(num_attr)
    except ValueError:
        num = idx
    label = _text(p.find("ParagraphNum"))
    if not label and num > 1:
        label = str(num).translate(_FULLWIDTH)
    lines = [_sentences(p.find("ParagraphSentence"))]
    for item in p.findall("Item"):
        lines.extend(_item_text(item))
    # Tables inside 項 (TableStruct) – take raw text row by row
    for ts in p.findall(".//TableStruct"):
        for row in ts.iter("TableRow"):
            cells = [_text(c) for c in row.findall("TableColumn")]
            if any(cells):
                lines.append(" | ".join(cells))
    return Paragraph(num=num, label=label, text="\n".join(x for x in lines if x))


def _parse_article(el: etree._Element, law_id: str, path: list[str], order: int, key_prefix: str = "",
                   is_suppl: bool = False) -> Article:
    num = el.get("Num") or str(order)
    title = _text(el.find("ArticleTitle"))
    caption = _text(el.find("ArticleCaption"))
    paragraphs = [_paragraph(p, i + 1) for i, p in enumerate(el.findall("Paragraph"))]
    return Article(
        law_id=law_id,
        article_key=f"{key_prefix}{num}",
        title=title,
        caption=caption,
        path=list(path),
        paragraphs=paragraphs,
        order=order,
        is_suppl=is_suppl,
    )


def _walk(el: etree._Element, law_id: str, path: list[str], out: list[Article]) -> None:
    for child in el:
        tag = child.tag
        if tag in _CONTAINER_TITLES:
            title = _text(child.find(_CONTAINER_TITLES[tag]))
            _walk(child, law_id, path + [title] if title else path, out)
        elif tag == "Article":
            out.append(_parse_article(child, law_id, path, len(out)))


def meta_from_xml(root: etree._Element, law_id: str, revision_id: str = "") -> LawMeta:
    law_title_el = root.find("LawBody/LawTitle")
    era = _ERA.get(root.get("Era", ""), root.get("Era", ""))
    y, m, d = root.get("Year", ""), root.get("PromulgateMonth", ""), root.get("PromulgateDay", "")
    return LawMeta(
        law_id=law_id,
        title=_text(law_title_el),
        law_num=_text(root.find("LawNum")),
        abbrev=(law_title_el.get("Abbrev", "") if law_title_el is not None else "").split(",")[0],
        law_type=root.get("LawType", ""),
        revision_id=revision_id,
        promulgation_date=f"{era}{y}年{m}月{d}日" if y else "",
    )


def parse_egov_xml(xml: bytes | str, meta: LawMeta | None = None, *, law_id: str | None = None,
                   revision_id: str = "", include_suppl: bool = False) -> ParsedLaw:
    if isinstance(xml, str):
        xml = xml.encode("utf-8")
    root = etree.fromstring(xml, parser=etree.XMLParser(huge_tree=True, recover=True))
    if root.tag != "Law":
        found = root.find(".//Law")
        if found is None:
            raise ValueError("Không tìm thấy phần tử <Law> trong XML")
        root = found
    if meta is None:
        if not law_id:
            raise ValueError("Cần law_id hoặc meta")
        meta = meta_from_xml(root, law_id, revision_id)
    else:
        xml_meta = meta_from_xml(root, meta.law_id, meta.revision_id)
        meta.title = meta.title or xml_meta.title
        meta.law_num = meta.law_num or xml_meta.law_num
        meta.abbrev = meta.abbrev or xml_meta.abbrev
        meta.law_type = meta.law_type or xml_meta.law_type

    articles: list[Article] = []
    main = root.find("LawBody/MainProvision")
    if main is not None:
        _walk(main, meta.law_id, [], articles)
        if not articles:  # short law: MainProvision holds only Paragraphs
            paras = [_paragraph(p, i + 1) for i, p in enumerate(main.findall("Paragraph"))]
            if paras:
                articles.append(Article(law_id=meta.law_id, article_key="main", title="本則",
                                        paragraphs=paras, order=0))

    if include_suppl:
        for si, sp in enumerate(root.findall("LawBody/SupplProvision")):
            label = _text(sp.find("SupplProvisionLabel")) or "附則"
            amend = sp.get("AmendLawNum", "")
            path = [f"{label}（{amend}）" if amend else label]
            prefix = f"suppl{si}_"
            arts = sp.findall(".//Article")
            if arts:
                for a in arts:
                    art = _parse_article(a, meta.law_id, path, len(articles), prefix, True)
                    art.title = f"{label}{art.title}"
                    articles.append(art)
            else:
                paras = [_paragraph(p, i + 1) for i, p in enumerate(sp.findall("Paragraph"))]
                if paras:
                    articles.append(Article(law_id=meta.law_id, article_key=f"{prefix}0", title=label,
                                            path=path, paragraphs=paras, order=len(articles), is_suppl=True))

    return ParsedLaw(meta=meta, articles=articles, aliases={})


_BULK_NAME_RE = re.compile(r"^(?P<law_id>[0-9A-Z]{15})(?:_(?P<rest>.+))?$")


def ids_from_filename(path: str | Path) -> tuple[str | None, str]:
    """'322AC0000000049_20260717_508AC0000000060.xml' -> ('322AC0000000049', '322AC..._20260717_...')"""
    stem = Path(path).stem
    m = _BULK_NAME_RE.match(stem)
    if not m:
        return None, ""
    return m.group("law_id"), stem if m.group("rest") else ""
