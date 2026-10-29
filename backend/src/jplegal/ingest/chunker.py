"""Split into chunks by 項 (paragraph). One 項 = one chunk so ただし書/号 stay addressable."""

from __future__ import annotations

from jplegal.core.models import Article, Chunk, ParsedLaw


def _header(law_title: str, art: Article, para_num: int) -> str:
    path = " > ".join(art.path)
    head = f"{law_title} {art.heading} 第{para_num}項".strip()
    return f"{head}\n{path}" if path else head


def build_chunks(parsed: ParsedLaw, max_chars: int = 2400) -> list[Chunk]:
    title = parsed.meta.title
    chunks: list[Chunk] = []
    for art in parsed.articles:
        paras = [p for p in art.paragraphs if p.text] or None
        units = paras if paras else []
        if not units:
            line = art.heading
            chunks.append(_chunk(art, title, 1, 0, line, False))
            continue
        for i, p in enumerate(units):
            line = f"{p.label}　{p.text}" if p.label else p.text
            proviso = "ただし" in p.text
            if len(line) <= max_chars:
                chunks.append(_chunk(art, title, p.num, i, line, proviso))
                continue
            part = 0
            rest = line
            while rest:
                if len(rest) <= max_chars:
                    chunks.append(_chunk(art, title, p.num, i * 100 + part, rest, proviso))
                    break
                cut = rest.rfind("。", 0, max_chars)
                cut = cut + 1 if cut > max_chars // 3 else max_chars
                chunks.append(_chunk(art, title, p.num, i * 100 + part, rest[:cut], proviso))
                rest = rest[cut:]
                part += 1
    return chunks


def _chunk(art: Article, law_title: str, para_num: int, part: int, text: str, proviso: bool) -> Chunk:
    header = _header(law_title, art, para_num)
    return Chunk(
        chunk_uid=f"{art.uid}~p{para_num}~{part}",
        article_uid=art.uid,
        law_id=art.law_id,
        law_title=law_title,
        article_key=art.article_key,
        article_title=art.title,
        caption=art.caption,
        path=" > ".join(art.path),
        text=text,
        embed_text=f"{header}\n{text}",
        part=part,
        para_num=para_num,
        proviso=proviso,
    )
