"""Ingest pipeline – shared by Batch (e-Gov) and Upload.

    parse → chunk → embed → Qdrant → Neo4j → legal_refs (PostgreSQL) → rebuild_links
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from sqlalchemy import delete, select

from jplegal.core.models import ParsedLaw
from jplegal.db.models import Document, LawRecord, LegalRef
from jplegal.ingest.chunker import build_chunks
from jplegal.ingest.linker import rebuild_links
from jplegal.ingest.parsers.egov_xml import ids_from_filename, parse_egov_xml
from jplegal.ingest.parsers.text_doc import extract_text, parse_text_document
from jplegal.ingest.ref_extractor import extract_references
from jplegal.ingest.terms import extract_terms

log = logging.getLogger(__name__)
Progress = Callable[[int, str], Awaitable[None]]


async def _noop(_: int, __: str) -> None:
    return None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def ingest_parsed_law(c, parsed: ParsedLaw, progress: Progress = _noop, *, link: bool = True) -> dict:
    s = c.settings
    meta = parsed.meta
    if not parsed.articles:
        raise ValueError(f"{meta.title or meta.law_id}から条文を抽出できませんでした")

    await progress(10, f"{len(parsed.articles)}条を項単位でチャンク化")
    chunks = build_chunks(parsed, s.max_chunk_chars)

    await progress(20, f"Embedding {len(chunks)} chunk")
    vectors: list[list[float]] = []
    bs = max(s.embed_batch_size * 4, 32)
    for i in range(0, len(chunks), bs):
        vectors += await c.models.embed([ch.embed_text for ch in chunks[i : i + bs]])
        await progress(20 + int(50 * min(1.0, (i + bs) / len(chunks))), f"Embedding {min(i + bs, len(chunks))}/{len(chunks)}")

    await progress(72, "Qdrantへ書き込み")
    if s.keep_revisions:
        await c.qdrant.mark_law_not_current(meta.law_id)
    else:
        await c.qdrant.delete_law(meta.law_id)
    sparse = None
    if await c.qdrant.has_sparse():  # always compute BM25 when the collection supports it (sparse branch toggled at query time)
        sparse = [c.sparse_doc({"law_title": ch.law_title, "article_title": ch.article_title,
                                "caption": ch.caption, "text": ch.text}) for ch in chunks]
    await c.qdrant.upsert_chunks(chunks, vectors, extra={"law_type": meta.law_type, "source": meta.source,
                                                          "revision_id": meta.revision_id,
                                                          "enforcement_date": meta.enforcement_date or meta.promulgation_date},
                                 sparse=sparse)

    await progress(80, "Neo4jへ書き込み")
    aliases, refs = extract_references(parsed)
    await c.neo4j.upsert_law_graph(parsed)
    await c.neo4j.upsert_terms(extract_terms(parsed))

    await progress(88, f"{len(refs)}件の引用を保存")
    async with c.db.session() as db:
        rec = await db.get(LawRecord, meta.law_id) or LawRecord(law_id=meta.law_id)
        rec.title, rec.abbrev, rec.law_num, rec.law_type = meta.title, meta.abbrev, meta.law_num, meta.law_type
        rec.category, rec.revision_id, rec.source = meta.category, meta.revision_id, meta.source
        rec.promulgation_date, rec.enforcement_date = meta.promulgation_date, meta.enforcement_date
        rec.document_id, rec.num_articles, rec.num_chunks, rec.aliases = (
            meta.document_id, len(parsed.articles), len(chunks), aliases)
        db.add(rec)
        await db.execute(delete(LegalRef).where(LegalRef.src_law_id == meta.law_id))
        db.add_all([
            LegalRef(src_uid=r.src_uid, src_law_id=r.src_law_id, relation=r.relation.value,
                     target_law_name=r.target_law_name, target_article_key=r.target_article_key,
                     raw_span=r.raw_span[:500])
            for r in refs
        ])
        await db.commit()

    link_stats = {}
    if link:
        await progress(94, "グラフを接続")
        link_stats = await rebuild_links(c, {meta.law_id})
    await progress(100, "完了")
    return {"law_id": meta.law_id, "title": meta.title, "articles": len(parsed.articles), "chunks": len(chunks),
            "refs": len(refs), **link_stats}


def parse_file(path: Path, *, document_id: str, include_suppl: bool, max_chars: int) -> ParsedLaw:
    """Detect upload file type and parse."""
    data = path.read_bytes()
    if path.suffix.lower() == ".xml" or data[:200].lstrip().startswith(b"<?xml") or b"<Law " in data[:2000]:
        law_id, revision_id = ids_from_filename(path.name)
        law_id = law_id or f"xml-{sha256_bytes(data)[:12]}"
        parsed = parse_egov_xml(data, law_id=law_id, revision_id=revision_id, include_suppl=include_suppl)
        parsed.meta.source = "upload"
    else:
        text = extract_text(path)
        title = _guess_title(text) or path.stem
        parsed = parse_text_document(text, law_id=f"upload-{document_id[:12]}", title=title, max_chars=max_chars)
    parsed.meta.document_id = document_id
    return parsed


def _guess_title(text: str) -> str:
    for ln in text.splitlines()[:15]:
        ln = ln.strip()
        if 2 <= len(ln) <= 60 and not ln.startswith("第") and (ln.endswith(("法", "令", "規則", "規程", "規定", "要領", "通達"))):
            return ln
    return ""


async def find_duplicate(c, content_hash: str) -> Document | None:
    async with c.db.session() as db:
        res = await db.execute(select(Document).where(Document.content_hash == content_hash,
                                                      Document.status == "done"))
        return res.scalars().first()
