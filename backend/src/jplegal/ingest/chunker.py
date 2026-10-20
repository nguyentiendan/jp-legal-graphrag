"""Split into chunks by article (条). Overlong articles → split by 項 groups."""

from __future__ import annotations

from jplegal.core.models import Article, Chunk, ParsedLaw


def _header(law_title: str, art: Article) -> str:
    path = " > ".join(art.path)
    head = f"{law_title} {art.heading}".strip()
    return f"{head}\n{path}" if path else head


def build_chunks(parsed: ParsedLaw, max_chars: int = 2400) -> list[Chunk]:
    title = parsed.meta.title
    chunks: list[Chunk] = []
    for art in parsed.articles:
        header = _header(title, art)
        groups: list[list[str]] = [[]]
        size = 0
        for p in art.paragraphs:
            line = f"{p.label}　{p.text}" if p.label else p.text
            if not line:
                continue
            if size and size + len(line) > max_chars:
                groups.append([])
                size = 0
            # 1 overlong 項 → hard-split by sentence
            while len(line) > max_chars:
                cut = line.rfind("。", 0, max_chars)
                cut = cut + 1 if cut > max_chars // 3 else max_chars
                groups[-1].append(line[:cut])
                groups.append([])
                line = line[cut:]
            groups[-1].append(line)
            size += len(line)
        groups = [g for g in groups if g]
        if not groups:
            groups = [[art.heading]]
        for i, g in enumerate(groups):
            text = "\n".join(g)
            chunks.append(
                Chunk(
                    chunk_uid=f"{art.uid}~{i}",
                    article_uid=art.uid,
                    law_id=art.law_id,
                    law_title=title,
                    article_key=art.article_key,
                    article_title=art.title,
                    caption=art.caption,
                    path=" > ".join(art.path),
                    text=text,
                    embed_text=f"{header}\n{text}",
                    part=i,
                )
            )
    return chunks
