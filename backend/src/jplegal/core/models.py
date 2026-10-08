"""Domain models dùng chung giữa ingest và retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Relation(StrEnum):
    REFERS_TO = "REFERS_TO"
    APPLIES_MUTATIS_MUTANDIS = "APPLIES_MUTATIS_MUTANDIS"  # 準用
    DELEGATES_TO = "DELEGATES_TO"  # 委任: 法律 → 政令/省令


def article_uid(law_id: str, article_key: str) -> str:
    """Khoá chung giữa Qdrant / Neo4j / PostgreSQL."""
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
    label: str  # "２" / "" (項1 thường không có số)
    text: str  # đã gồm cả 号 (item) bên trong


@dataclass
class Article:
    law_id: str
    article_key: str  # "32_2" (theo thuộc tính Num của e-Gov XML), "suppl1_3", "c1" (upload không có 条)
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
    aliases: dict[str, str] = field(default_factory=dict)  # 「法」→「労働基準法」 (định nghĩa 以下「…」という)


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
    text: str  # nội dung chunk (không kèm prefix)
    embed_text: str  # header + nội dung, dùng để embedding
    part: int = 0


@dataclass
class RawReference:
    """Dẫn chiếu thô trích ra từ văn bản, chưa resolve sang law_id."""

    src_uid: str
    src_law_id: str
    relation: Relation
    raw_span: str
    target_law_name: str | None = None  # None = cùng luật
    target_article_key: str | None = None  # None = tham chiếu tới cả luật (vd. 委任)
    target_law_suffix: str | None = None  # "施行令" / "施行規則" cho 委任
