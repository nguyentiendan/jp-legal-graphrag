"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Card, ErrorBox, Skeleton } from "@/components/ui";
import { api, type LawDetail } from "@/lib/api";
import { useT } from "@/lib/i18n";

function LawView() {
  const { t } = useT();
  const id = useSearchParams().get("id") ?? "";
  const [law, setLaw] = useState<LawDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (id) api.law(id).then(setLaw).catch((e) => setError(String(e)));
  }, [id]);

  if (error) return <ErrorBox message={error} />;
  if (!law) return <Skeleton className="h-64 w-full" />;

  let lastPath = "";
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="min-w-0">
        <Link href="/laws/" className="text-sm text-muted hover:text-ink">
          ← {t("common.back")}
        </Link>
        <h1 className="mt-2 font-serif text-2xl font-semibold">{law.title}</h1>
        <p className="mt-1 text-sm text-muted">
          {law.law_num} · {law.law_type} · <span className="font-mono">{law.law_id}</span>
        </p>
        <Card className="mt-5">
          <ul>
            {law.articles.map((a) => {
              const header = a.path && a.path !== lastPath ? a.path : null;
              lastPath = a.path;
              return (
                <li key={a.uid}>
                  {header && (
                    <div className="border-b border-line bg-surface-2/60 px-5 py-2 text-xs font-medium text-muted">
                      {header}
                    </div>
                  )}
                  <Link
                    href={`/articles/view/?uid=${encodeURIComponent(a.uid)}`}
                    className="flex items-baseline gap-3 border-b border-line px-5 py-2.5 text-sm hover:bg-surface-2/60"
                  >
                    <span className="w-28 shrink-0 font-medium">{a.title}</span>
                    <span className="truncate text-muted">{a.caption}</span>
                    {a.degree > 0 && (
                      <span className="ml-auto shrink-0 text-xs text-muted">
                        {a.degree} {t("laws.degree")}
                      </span>
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </Card>
      </div>
      <aside className="space-y-6">
        {Object.keys(law.aliases ?? {}).length > 0 && (
          <Card className="p-4">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">{t("laws.aliases")}</h3>
            <dl className="space-y-1 text-sm">
              {Object.entries(law.aliases).map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <dt className="font-medium">「{k}」</dt>
                  <dd className="text-muted">{v}</dd>
                </div>
              ))}
            </dl>
          </Card>
        )}
        {law.unresolved_targets.length > 0 && (
          <Card className="p-4">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">{t("laws.unresolved")}</h3>
            <ul className="space-y-1 text-sm">
              {law.unresolved_targets.map((u) => (
                <li key={u.name ?? "self"} className="flex justify-between gap-2">
                  <span className="truncate" title={u.name}>
                    {u.name}
                  </span>
                  <span className="text-muted">{u.count}</span>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </aside>
    </div>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<Skeleton className="h-64 w-full" />}>
      <LawView />
    </Suspense>
  );
}
