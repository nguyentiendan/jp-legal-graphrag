"""Resolve dẫn chiếu thô (legal_refs) → cạnh trong Neo4j.

PostgreSQL.legal_refs là nguồn sự thật. Mỗi khi ingest 1 luật mới, chạy lại cho:
  * refs của chính luật đó,
  * refs chưa resolve (có thể giờ đã trỏ được tới luật vừa nạp),
  * refs đang trỏ tới luật đó (để dựng lại cạnh sau khi re-ingest).
"""

from __future__ import annotations

import logging

from sqlalchemy import or_, select, update

from jplegal.core.models import Relation, article_uid
from jplegal.db.models import LawRecord, LegalRef
from jplegal.ingest.ref_extractor import parent_title

log = logging.getLogger(__name__)


class LawRegistry:
    def __init__(self, laws: list[LawRecord]):
        self.by_name: dict[str, str] = {}
        self.titles: dict[str, str] = {}
        for law in laws:
            self.titles[law.title] = law.law_id
            self.by_name[law.title] = law.law_id
            if law.abbrev:
                self.by_name.setdefault(law.abbrev, law.law_id)

    def resolve(self, name: str | None) -> str | None:
        if not name:
            return None
        if name in self.by_name:
            return self.by_name[name]
        # tên thô có thể dính tiền tố rác: '受ける職業訓練の訓練課程に応じ職業能力開発促進法施行規則'
        best = max((n for n in self.by_name if len(n) >= 3 and name.endswith(n)), key=len, default=None)
        if best:
            return self.by_name[best]
        # tên thô bị cắt mất đầu: '行う労働者の福祉に関する法律'
        if len(name) >= 6:
            cands = [t for t in self.titles if t.endswith(name)]
            if len(cands) == 1:
                return self.titles[cands[0]]
        return None


async def rebuild_links(c, law_ids: set[str] | None = None) -> dict:
    async with c.db.session() as s:
        laws = list((await s.execute(select(LawRecord))).scalars())
        registry = LawRegistry(laws)
        q = select(LegalRef)
        if law_ids:
            q = q.where(or_(LegalRef.src_law_id.in_(law_ids), LegalRef.resolved.is_(False),
                            LegalRef.target_law_id.in_(law_ids)))
        refs = list((await s.execute(q)).scalars())

        art_rows: list[dict] = []
        law_rows: list[dict] = []
        newly_resolved: dict[int, str] = {}
        for r in refs:
            tgt = r.src_law_id if r.target_law_name is None else registry.resolve(r.target_law_name)
            if tgt is None:
                continue
            if not r.resolved or r.target_law_id != tgt:
                newly_resolved[r.id] = tgt
            if r.target_article_key:
                art_rows.append({"src": r.src_uid, "dst": article_uid(tgt, r.target_article_key),
                                 "rel": r.relation, "raw": r.raw_span})
            elif r.relation == Relation.DELEGATES_TO.value:
                law_rows.append({"src": r.src_uid, "dst_law": tgt, "raw": r.raw_span})

        for rid, tgt in newly_resolved.items():
            await s.execute(update(LegalRef).where(LegalRef.id == rid).values(resolved=True, target_law_id=tgt))
        await s.commit()

    n_art = await c.neo4j.link_article_edges(art_rows)
    n_law = await c.neo4j.link_article_to_law(law_rows)

    pairs = []
    for law in laws:
        p = parent_title(law.title)
        if p and p in registry.titles:
            pairs.append({"parent": registry.titles[p], "child": law.law_id})
    await c.neo4j.link_law_delegations(pairs)
    stats = {"refs_considered": len(refs), "article_edges": n_art, "delegation_edges": n_law,
             "law_delegations": len(pairs), "newly_resolved": len(newly_resolved)}
    log.info("rebuild_links %s", stats)
    return stats
