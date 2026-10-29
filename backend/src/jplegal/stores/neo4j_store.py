"""Neo4j – structure + reference graph.

(:Law {law_id, title, abbrev, law_type, law_num, revision_id, ...})
(:Article {uid, law_id, article_key, title, caption, path, text, law_title, order})
(:Law)-[:HAS_ARTICLE]->(:Article)      (:Article)-[:NEXT]->(:Article)
(:Article)-[:REFERS_TO|APPLIES_MUTATIS_MUTANDIS]->(:Article)
(:Article)-[:DELEGATES_TO]->(:Law)       (:Law)-[:DELEGATES_TO]->(:Law)   (法律 → 施行令/施行規則)
(:Article)-[:DEFINES]->(:Term)           (:Term)-[:DEFINED_IN]->(:Article)
"""

from __future__ import annotations

from dataclasses import dataclass

from neo4j import AsyncDriver, AsyncGraphDatabase

from jplegal.core.models import LawMeta, ParsedLaw, Relation

REF_RELS = "REFERS_TO|APPLIES_MUTATIS_MUTANDIS|DELEGATES_TO"


def keep_incoming(rel: str, outgoing: bool, in_degree: int, max_in: int) -> bool:
    """Drop incoming REFERS_TO into hub articles (定義条 etc.)."""
    if outgoing:
        return True
    if rel == "REFERS_TO" and in_degree > max_in:
        return False
    return True


@dataclass
class GraphEdge:
    src: str
    rel: str
    dst: str
    outgoing: bool  # True: src -> dst
    dst_kind: str  # Article | Law
    raw_span: str = ""
    in_degree: int = 0


class Neo4jStore:
    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j"):
        self.driver: AsyncDriver = AsyncGraphDatabase.driver(uri, auth=(user, password))
        self.database = database

    async def close(self) -> None:
        await self.driver.close()

    async def _run(self, query: str, **params) -> list[dict]:
        async with self.driver.session(database=self.database) as s:
            res = await s.run(query, **params)
            return [r.data() async for r in res]

    async def ensure_schema(self) -> None:
        for q in (
            "CREATE CONSTRAINT law_id IF NOT EXISTS FOR (l:Law) REQUIRE l.law_id IS UNIQUE",
            "CREATE CONSTRAINT article_uid IF NOT EXISTS FOR (a:Article) REQUIRE a.uid IS UNIQUE",
            "CREATE CONSTRAINT term_name IF NOT EXISTS FOR (t:Term) REQUIRE t.name IS UNIQUE",
            "CREATE INDEX article_law IF NOT EXISTS FOR (a:Article) ON (a.law_id)",
            "CREATE INDEX law_title IF NOT EXISTS FOR (l:Law) ON (l.title)",
        ):
            await self._run(q)

    # ------------------------------------------------------------------ write
    async def upsert_law_graph(self, parsed: ParsedLaw) -> None:
        m: LawMeta = parsed.meta
        law_props = {
            "title": m.title, "abbrev": m.abbrev, "law_type": m.law_type, "law_num": m.law_num,
            "revision_id": m.revision_id, "category": m.category, "source": m.source,
            "promulgation_date": m.promulgation_date, "enforcement_date": m.enforcement_date,
            "ingested": True,
        }
        arts = [
            {"uid": a.uid, "law_id": a.law_id, "article_key": a.article_key, "title": a.title,
             "caption": a.caption, "path": " > ".join(a.path), "text": a.text, "law_title": m.title,
             "order": a.order, "is_suppl": a.is_suppl}
            for a in parsed.articles
        ]
        uids = [a["uid"] for a in arts]
        await self._run("MERGE (l:Law {law_id:$law_id}) SET l += $props", law_id=m.law_id, props=law_props)
        # drop outgoing reference edges (rebuilt later) + old NEXT + articles that no longer exist
        await self._run(
            f"MATCH (a:Article {{law_id:$law_id}})-[r:{REF_RELS}|NEXT]->() DELETE r", law_id=m.law_id
        )
        await self._run(
            "MATCH (a:Article {law_id:$law_id}) WHERE NOT a.uid IN $uids DETACH DELETE a",
            law_id=m.law_id, uids=uids,
        )
        for i in range(0, len(arts), 500):
            await self._run(
                """
                MATCH (l:Law {law_id:$law_id})
                UNWIND $arts AS a
                MERGE (n:Article {uid:a.uid})
                SET n += a
                MERGE (l)-[:HAS_ARTICLE]->(n)
                """,
                law_id=m.law_id, arts=arts[i : i + 500],
            )
        main = [a["uid"] for a in arts if not a["is_suppl"]]
        pairs = [{"a": x, "b": y} for x, y in zip(main, main[1:])]
        if pairs:
            await self._run(
                "UNWIND $pairs AS p MATCH (a:Article {uid:p.a}), (b:Article {uid:p.b}) MERGE (a)-[:NEXT]->(b)",
                pairs=pairs,
            )

    async def link_article_edges(self, rows: list[dict]) -> int:
        """rows: {src, dst, rel, raw} – dst is an Article.uid. Only create an edge when both nodes exist."""
        total = 0
        for rel in (Relation.REFERS_TO, Relation.APPLIES_MUTATIS_MUTANDIS, Relation.DELEGATES_TO):
            part = [r for r in rows if r["rel"] == rel.value]
            for i in range(0, len(part), 1000):
                res = await self._run(
                    f"""
                    UNWIND $rows AS r
                    MATCH (a:Article {{uid:r.src}}), (b:Article {{uid:r.dst}})
                    MERGE (a)-[e:{rel.value}]->(b) SET e.raw_span = r.raw
                    RETURN count(e) AS c
                    """,
                    rows=part[i : i + 1000],
                )
                total += res[0]["c"] if res else 0
        return total

    async def link_article_to_law(self, rows: list[dict]) -> int:
        """rows: {src, dst_law, raw} – 委任: Article -[:DELEGATES_TO]-> Law."""
        if not rows:
            return 0
        res = await self._run(
            """
            UNWIND $rows AS r
            MATCH (a:Article {uid:r.src}), (l:Law {law_id:r.dst_law})
            MERGE (a)-[e:DELEGATES_TO]->(l) SET e.raw_span = r.raw
            RETURN count(e) AS c
            """,
            rows=rows,
        )
        return res[0]["c"] if res else 0

    async def link_law_delegations(self, pairs: list[dict]) -> None:
        """pairs: {parent, child} – (法律)-[:DELEGATES_TO]->(施行令/施行規則)."""
        if pairs:
            await self._run(
                """
                UNWIND $pairs AS p
                MATCH (a:Law {law_id:p.parent}), (b:Law {law_id:p.child})
                MERGE (a)-[:DELEGATES_TO]->(b)
                """,
                pairs=pairs,
            )

    async def delete_law(self, law_id: str) -> None:
        await self._run("MATCH (a:Article {law_id:$law_id}) DETACH DELETE a", law_id=law_id)
        await self._run("MATCH (l:Law {law_id:$law_id}) DETACH DELETE l", law_id=law_id)

    # ------------------------------------------------------------------ read
    async def upsert_terms(self, rows: list[dict]) -> None:
        """rows: {name, uid, body}."""
        if not rows:
            return
        await self._run(
            """
            UNWIND $rows AS r
            MATCH (a:Article {uid:r.uid})
            MERGE (t:Term {name:r.name})
            SET t.body = r.body
            MERGE (a)-[:DEFINES]->(t)
            MERGE (t)-[:DEFINED_IN]->(a)
            """,
            rows=rows,
        )

    async def articles_for_terms(self, query: str) -> list[str]:
        if not query.strip():
            return []
        rows = await self._run(
            """
            MATCH (t:Term)-[:DEFINED_IN]->(a:Article)
            WHERE $q CONTAINS t.name
            RETURN DISTINCT a.uid AS uid
            """,
            q=query,
        )
        return [r["uid"] for r in rows]

    async def child_law_ids(self, parent_ids: list[str]) -> list[str]:
        if not parent_ids:
            return []
        rows = await self._run(
            """
            MATCH (p:Law)-[:DELEGATES_TO]->(c:Law)
            WHERE p.law_id IN $ids
            RETURN DISTINCT c.law_id AS id
            """,
            ids=parent_ids,
        )
        return [r["id"] for r in rows]

    async def expand(self, seeds: list[str], limit: int = 500, max_in_degree: int = 8) -> list[GraphEdge]:
        if not seeds:
            return []
        rows = await self._run(
            f"""
            MATCH (a:Article) WHERE a.uid IN $seeds
            MATCH (a)-[r:{REF_RELS}]-(b)
            WHERE b:Article OR b:Law
            WITH a, r, b, startNode(r) = a AS outgoing
            WITH a, r, b, outgoing,
                 CASE WHEN NOT outgoing AND type(r) = 'REFERS_TO' AND b:Article
                      THEN COUNT {{ (x)-[:REFERS_TO]->(b) }}
                      ELSE 0 END AS indeg
            WHERE outgoing OR type(r) <> 'REFERS_TO' OR indeg <= $max_in
            RETURN a.uid AS src, type(r) AS rel, outgoing,
                   CASE WHEN b:Article THEN 'Article' ELSE 'Law' END AS kind,
                   coalesce(b.uid, b.law_id) AS dst,
                   coalesce(r.raw_span, '') AS raw,
                   indeg
            LIMIT $limit
            """,
            seeds=seeds, limit=limit, max_in=max_in_degree,
        )
        return [
            GraphEdge(src=r["src"], rel=r["rel"], dst=r["dst"], outgoing=r["outgoing"],
                      dst_kind=r["kind"], raw_span=r.get("raw") or "", in_degree=int(r.get("indeg") or 0))
            for r in rows
        ]

    async def get_articles(self, uids: list[str]) -> dict[str, dict]:
        if not uids:
            return {}
        rows = await self._run(
            """
            MATCH (a:Article) WHERE a.uid IN $uids
            RETURN a.uid AS uid, a.law_id AS law_id, a.law_title AS law_title, a.article_key AS article_key,
                   a.title AS title, a.caption AS caption, a.path AS path, a.text AS text
            """,
            uids=uids,
        )
        return {r["uid"]: r for r in rows}

    async def subgraph(self, uids: list[str], hops: int = 1, limit: int = 150) -> dict:
        """Nodes + edges around articles (for FE rendering)."""
        if not uids:
            return {"nodes": [], "edges": []}
        rows = await self._run(
            f"""
            MATCH (a:Article) WHERE a.uid IN $uids
            OPTIONAL MATCH (a)-[r:{REF_RELS}]-(b)
            WITH a, r, b LIMIT $limit
            RETURN a.uid AS a_uid, a.law_title AS a_law, a.title AS a_title, a.caption AS a_caption,
                   type(r) AS rel, startNode(r) = a AS outgoing,
                   CASE WHEN b IS NULL THEN NULL WHEN b:Article THEN 'Article' ELSE 'Law' END AS b_kind,
                   coalesce(b.uid, b.law_id) AS b_id, coalesce(b.law_title, b.title) AS b_law,
                   b.title AS b_title, b.caption AS b_caption
            """,
            uids=uids, limit=limit,
        )
        nodes: dict[str, dict] = {}
        edges: list[dict] = []
        for r in rows:
            nodes.setdefault(r["a_uid"], {"id": r["a_uid"], "kind": "Article", "law": r["a_law"],
                                          "label": f"{r['a_law']} {r['a_title']}", "caption": r["a_caption"],
                                          "seed": True})
            nodes[r["a_uid"]]["seed"] = True
            if r["b_id"] is None:
                continue
            label = r["b_law"] if r["b_kind"] == "Law" else f"{r['b_law']} {r['b_title']}"
            nodes.setdefault(r["b_id"], {"id": r["b_id"], "kind": r["b_kind"], "law": r["b_law"], "label": label,
                                         "caption": r["b_caption"] or "", "seed": False})
            src, dst = (r["a_uid"], r["b_id"]) if r["outgoing"] else (r["b_id"], r["a_uid"])
            edges.append({"source": src, "target": dst, "rel": r["rel"]})
        uniq = {(e["source"], e["target"], e["rel"]): e for e in edges}
        return {"nodes": list(nodes.values()), "edges": list(uniq.values())}

    async def law_articles(self, law_id: str) -> list[dict]:
        return await self._run(
            """
            MATCH (:Law {law_id:$law_id})-[:HAS_ARTICLE]->(a:Article)
            OPTIONAL MATCH (a)-[r:REFERS_TO|APPLIES_MUTATIS_MUTANDIS|DELEGATES_TO]-()
            RETURN a.uid AS uid, a.article_key AS article_key, a.title AS title, a.caption AS caption,
                   a.path AS path, a.order AS order, count(r) AS degree
            ORDER BY a.order
            """,
            law_id=law_id,
        )

    async def stats(self) -> dict:
        rows = await self._run(
            """
            CALL () { MATCH (l:Law) RETURN count(l) AS laws }
            CALL () { MATCH (a:Article) RETURN count(a) AS articles }
            CALL () { MATCH ()-[r:REFERS_TO|APPLIES_MUTATIS_MUTANDIS|DELEGATES_TO]->() RETURN count(r) AS refs }
            RETURN laws, articles, refs
            """
        )
        return rows[0] if rows else {}
