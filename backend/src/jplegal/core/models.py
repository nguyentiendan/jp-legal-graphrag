"""Domain models shared between ingest and retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Relation(StrEnum):
    REFERS_TO = "REFERS_TO"
    APPLIES_MUTATIS_MUTANDIS = "APPLIES_MUTATIS_MUTANDIS"  # 準用
    DELEGATES_TO = "DELEGATES_TO"  # 委任: 法律 → 政令/省令


def article_uid(law_id: str, article_key: str) -> str:
    """Shared key across Qdrant / Neo4j / PostgreSQL."""
    return f"{law_id}#{article_key}"


@dataclass
class LawMeta:
    law_id: str
    title: str
    law_num: str = ""
    abbrev: str = ""
    law_type: str = ""  # Act / CabinetOrder / MinisterialOrdinance / ... / Upload
    category: str = ""
    revision_id: str = ""
    promulgation_date: str = ""
    enforcement_date: str = ""
    source: str = "egov"  # egov | upload
    document_id: str | None = None


@dataclass
class Paragraph:
    num: int
    label: str  # "２" / "" (項1 usually has no number)
    text: str  # already includes 号 (item) inside


@dataclass
class Article:
    law_id: str
    article_key: str  # "32_2" (from the Num attribute of e-Gov XML), "suppl1_3", "c1" (uploads without 条)
    title: str  # "第三十二条の二"
    caption: str = ""  # "（労働時間）"
    path: list[str] = field(default_factory=list)  # ["第四章　労働時間、休憩、休日及び年次有給休暇"]
    paragraphs: list[Paragraph] = field(default_factory=list)
    order: int = 0
    is_suppl: bool = False

    @property
    def uid(self) -> str:
        return article_uid(self.law_id, self.article_key)

    @property
    def text(self) -> str:
        return "\n".join(
            (f"{p.label}　{p.text}" if p.label else p.text) for p in self.paragraphs if p.text
        ).strip()

    @property
    def heading(self) -> str:
        return f"{self.title}{self.caption}"


@dataclass
class ParsedLaw:
    meta: LawMeta
    articles: list[Article]
    aliases: dict[str, str] = field(default_factory=dict)  # 「法」→「労働基準法」 (definitions like 以下「…」という)


@dataclass
class Chunk:
    chunk_uid: str
    article_uid: str
    law_id: str
    law_title: str
    article_key: str
    article_title: str
    caption: str
    path: str
    text: str  # chunk content (without prefix)
    embed_text: str  # header + content, used for embedding
    part: int = 0


@dataclass
class RawReference:
    """Raw reference extracted from text, not yet resolved to a law_id."""

    src_uid: str
    src_law_id: str
    relation: Relation
    raw_span: str
    target_law_name: str | None = None  # None = same law
    target_article_key: str | None = None  # None = reference to the whole law (e.g. 委任)
    target_law_suffix: str | None = None  # "施行令" / "施行規則" cho 委任
