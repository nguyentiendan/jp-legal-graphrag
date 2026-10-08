"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { GraphView } from "@/components/GraphView";
import { Card, ErrorBox, Skeleton } from "@/components/ui";
import { api, type ArticleDetail, type Subgraph } from "@/lib/api";
import { useT } from "@/lib/i18n";

function ArticleView() {
  const { t } = useT();
  const router = useRouter();
  const uid = useSearchParams().get("uid") ?? "";
  const [data, setData] = useState<{ articles: ArticleDetail[]; graph: Subgraph } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!uid) return;
    setData(null);
    api.articleGraph([uid]).then(setData).catch((e) => setError(String(e)));
  }, [uid]);

  if (error) return <ErrorBox message={error} />;
  if (!data) return <Skeleton className="h-64 w-full" />;
  const a = data.articles[0];
  const neighbors = data.graph.nodes.filter((n) => n.id !== uid);
  const relOf = (id: string) =>
    data.graph.edges
      .filter((e) => (e.source === uid && e.target === id) || (e.target === uid && e.source === id))
      .map((e) => `${e.source === uid ? "→" : "←"} ${t(`rel.${e.rel}` as "rel.REFERS_TO")}`);

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_420px]">
      <div className="min-w-0">
        <Link href={`/laws/view/?id=${encodeURIComponent(a.law_id)}`} className="text-sm text-muted hover:text-ink">
          ← {a.law_title}
        </Link>
        <h1 className="mt-2 font-serif text-2xl font-semibold">
          {a.title}
          <span className="ml-2 text-lg font-normal text-muted">{a.caption}</span>
        </h1>
        {a.path && <p className="mt-1 text-sm text-muted">{a.path}</p>}
        <Card className="mt-5 p-6">
          <p className="law-text text-[15px]">{a.text}</p>
        </Card>
      </div>
      <aside className="space-y-4">
        <GraphView
          graph={data.graph}
          height={380}
          onNodeClick={(id, kind) => {
            if (kind === "Article") router.push(`/articles/view/?uid=${encodeURIComponent(id)}`);
            else router.push(`/laws/view/?id=${encodeURIComponent(id)}`);
          }}
        />
        <Card>
          <h3 className="border-b border-line px-4 py-2.5 text-xs font-semibold uppercase tracking-wider text-muted">
            {t("article.neighbors")} · {neighbors.length}
          </h3>
          <ul className="max-h-[420px] overflow-y-auto">
            {neighbors.map((n) => (
              <li key={n.id} className="border-b border-line last:border-0">
                <Link
                  href={
                    n.kind === "Article"
                      ? `/articles/view/?uid=${encodeURIComponent(n.id)}`
                      : `/laws/view/?id=${encodeURIComponent(n.id)}`
                  }
                  className="block px-4 py-2.5 text-sm hover:bg-surface-2/60"
                >
                  <div className="flex items-baseline gap-2">
                    <span className="font-medium">{n.label}</span>
                    <span className="truncate text-muted">{n.caption}</span>
                  </div>
                  <div className="mt-0.5 text-xs text-muted">{relOf(n.id).join(" · ")}</div>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      </aside>
    </div>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<Skeleton className="h-64 w-full" />}>
      <ArticleView />
    </Suspense>
  );
}
