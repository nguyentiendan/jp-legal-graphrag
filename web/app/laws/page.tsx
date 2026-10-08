"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, Empty, ErrorBox, Input, Skeleton } from "@/components/ui";
import { api, type Law } from "@/lib/api";
import { useT } from "@/lib/i18n";

export default function LawsPage() {
  const { t } = useT();
  const [laws, setLaws] = useState<Law[] | null>(null);
  const [stats, setStats] = useState<{ laws: number; articles: number; refs: number; points: number } | null>(null);
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setError(null);
    api.laws().then(setLaws).catch((e) => setError(String(e)));
    api
      .stats()
      .then((s) => setStats({ ...s.neo4j, points: s.qdrant_points }))
      .catch(() => {});
  };
  useEffect(load, []);

  const shown = (laws ?? []).filter((l) => !q || l.title.includes(q) || l.law_id.includes(q));

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end gap-4">
        <h1 className="text-xl font-semibold">{t("laws.title")}</h1>
        {stats && (
          <div className="flex gap-5 text-xs text-muted">
            <span>Law <b className="text-ink">{stats.laws}</b></span>
            <span>Article <b className="text-ink">{stats.articles}</b></span>
            <span>Edge <b className="text-ink">{stats.refs}</b></span>
            <span>Vector <b className="text-ink">{stats.points}</b></span>
          </div>
        )}
        <div className="ml-auto w-64">
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("laws.search")} />
        </div>
      </div>
      {error && <ErrorBox message={error} onRetry={load} />}
      {laws === null && !error && <Skeleton className="h-40 w-full" />}
      {laws?.length === 0 && <Empty>{t("laws.empty")}</Empty>}
      {shown.length > 0 && (
        <Card>
          <ul>
            {shown.map((l) => (
              <li key={l.law_id} className="border-b border-line last:border-0">
                <Link
                  href={`/laws/view/?id=${encodeURIComponent(l.law_id)}`}
                  className="flex flex-wrap items-baseline gap-x-4 gap-y-1 px-5 py-3.5 hover:bg-surface-2/60"
                >
                  <span className="font-medium">{l.title}</span>
                  {l.abbrev && <span className="text-xs text-muted">（{l.abbrev}）</span>}
                  <span className="text-xs text-muted">{l.law_num}</span>
                  <span className="ml-auto flex gap-4 text-xs text-muted">
                    <span>{l.law_type}</span>
                    <span>
                      {l.num_articles} {t("laws.articles")}
                    </span>
                    <span className="font-mono">{l.law_id}</span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
