"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { GraphView } from "@/components/GraphView";
import { Button, Card, cx, Empty, ErrorBox, Skeleton, SourceBadge, Textarea } from "@/components/ui";
import { api, ask, type Law, type RetrievalResult, type RetrievedItem } from "@/lib/api";
import { useT } from "@/lib/i18n";

function AnswerText({ text, streaming }: { text: string; streaming: boolean }) {
  const parts = text.split(/(\[[^\]\n]{2,60}\])/g);
  return (
    <div className={cx("answer-text text-[15px]", streaming && "caret")}>
      {parts.map((p, i) =>
        /^\[[^\]]+\]$/.test(p) ? (
          <span key={i} className="mx-0.5 rounded bg-ai-soft px-1 py-0.5 text-[13px] font-medium text-ai">
            {p.slice(1, -1)}
          </span>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </div>
  );
}

function EvidenceItem({ it, n }: { it: RetrievedItem; n: number }) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const preview = it.text.length > 220 && !open ? it.text.slice(0, 220) + "…" : it.text;
  return (
    <li className="border-b border-line px-5 py-4 last:border-b-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-muted">[{n}]</span>
        <Link
          href={`/articles/view/?uid=${encodeURIComponent(it.uid)}`}
          className="font-semibold text-ink hover:text-ai"
        >
          {it.citation}
        </Link>
        <span className="text-sm text-muted">{it.caption}</span>
        <span className="ml-auto flex gap-1">
          {it.sources.map((s) => (
            <SourceBadge key={s} s={s} />
          ))}
        </span>
      </div>
      {it.path && <div className="mt-0.5 text-xs text-muted">{it.path}</div>}
      <p className="law-text mt-2 text-sm">{preview}</p>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted">
        {it.text.length > 220 && (
          <button onClick={() => setOpen(!open)} className="text-ai hover:underline">
            {open ? t("ask.hideText") : t("ask.showText")}
          </button>
        )}
        {it.dense_rank && <span>dense #{it.dense_rank} · {it.dense_score?.toFixed(3)}</span>}
        {it.graph_rank && (
          <span>
            graph #{it.graph_rank}
            {it.graph_via[0] && (
              <>
                {" "}
                · {t("ask.via")} {t(`rel.${it.graph_via[0].rel}` as "rel.REFERS_TO")} ← {it.graph_via[0].from.split("#")[1]}
              </>
            )}
          </span>
        )}
        <span>fusion {it.rrf_score.toFixed(3)}</span>
        {it.rerank_score !== null && <span>rerank {it.rerank_score.toFixed(3)}</span>}
      </div>
    </li>
  );
}

export default function AskPage() {
  const { t } = useT();
  const [query, setQuery] = useState("");
  const [useGraph, setUseGraph] = useState(true);
  const [useRerank, setUseRerank] = useState(true);
  const [laws, setLaws] = useState<Law[] | null>(null);
  const [lawFilter, setLawFilter] = useState<string[]>([]);
  const [retrieval, setRetrieval] = useState<RetrievalResult | null>(null);
  const [answer, setAnswer] = useState("");
  const [phase, setPhase] = useState<"idle" | "retrieving" | "answering" | "done">("idle");
  const [error, setError] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    api.laws().then(setLaws).catch(() => setLaws([]));
  }, []);

  const run = async (searchOnly = false) => {
    if (!query.trim()) return;
    abort.current?.abort();
    const ctl = new AbortController();
    abort.current = ctl;
    setError(null);
    setAnswer("");
    setRetrieval(null);
    setPhase("retrieving");
    const body = { query, use_graph: useGraph, use_rerank: useRerank, law_ids: lawFilter.length ? lawFilter : null };
    try {
      if (searchOnly) {
        setRetrieval(await api.search(body));
        setPhase("done");
        return;
      }
      await ask(
        body,
        {
          onRetrieval: (r) => {
            setRetrieval(r);
            setPhase("answering");
          },
          onToken: (tok) => setAnswer((a) => a + tok),
          onDone: (d) => {
            setAnswer((a) => a || d.answer);
            setPhase("done");
          },
          onError: (m) => {
            setError(m);
            setPhase("done");
          },
        },
        ctl.signal,
      );
      setPhase("done");
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError(String(e));
      setPhase("done");
    }
  };

  const busy = phase === "retrieving" || phase === "answering";

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
      <div className="min-w-0 space-y-6">
        <Card className="p-4">
          <Textarea
            rows={3}
            value={query}
            placeholder={t("ask.placeholder")}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) run();
            }}
            className="resize-y border-0 bg-transparent px-1 text-[15px] focus:border-0"
          />
          <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-line pt-3">
            <label className="flex items-center gap-2 text-sm text-muted">
              <input type="checkbox" checked={useGraph} onChange={(e) => setUseGraph(e.target.checked)} />
              {t("ask.graph")}
            </label>
            <label className="flex items-center gap-2 text-sm text-muted">
              <input type="checkbox" checked={useRerank} onChange={(e) => setUseRerank(e.target.checked)} />
              {t("ask.rerank")}
            </label>
            <div className="ml-auto flex gap-2">
              {busy ? (
                <Button variant="outline" onClick={() => abort.current?.abort()}>
                  {t("ask.stop")}
                </Button>
              ) : (
                <Button variant="outline" onClick={() => run(true)} disabled={!query.trim()}>
                  {t("ask.searchOnly")}
                </Button>
              )}
              <Button onClick={() => run()} disabled={busy || !query.trim()}>
                {t("ask.submit")}
              </Button>
            </div>
          </div>
        </Card>

        {error && <ErrorBox message={error} onRetry={() => run()} />}

        {phase === "idle" && !retrieval && (
          <Empty>
            {laws && laws.length === 0 ? (
              <>
                {t("ask.noLaws")}{" "}
                <Link href="/ingest/" className="text-ai underline">
                  {t("nav.ingest")}
                </Link>
              </>
            ) : (
              t("ask.empty")
            )}
          </Empty>
        )}

        {(answer || phase === "answering") && (
          <Card className="p-5">
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted">{t("ask.answer")}</h2>
            {answer ? (
              <AnswerText text={answer} streaming={phase === "answering"} />
            ) : (
              <div className="space-y-2">
                <Skeleton className="h-4 w-11/12" />
                <Skeleton className="h-4 w-9/12" />
                <Skeleton className="h-4 w-10/12" />
              </div>
            )}
          </Card>
        )}

        {phase === "retrieving" && (
          <Card>
            {[0, 1, 2].map((i) => (
              <div key={i} className="space-y-2 border-b border-line px-5 py-4 last:border-0">
                <Skeleton className="h-4 w-1/3" />
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-4/5" />
              </div>
            ))}
          </Card>
        )}

        {retrieval && (
          <Card>
            <h2 className="border-b border-line px-5 py-3 text-xs font-semibold uppercase tracking-wider text-muted">
              {t("ask.evidence")} · {retrieval.items.length}
            </h2>
            <ol>
              {retrieval.items.map((it, i) => (
                <EvidenceItem key={it.uid} it={it} n={i + 1} />
              ))}
            </ol>
          </Card>
        )}
      </div>

      <aside className="space-y-6">
        <Card className="p-4">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">{t("ask.filterLaws")}</h3>
          {laws === null ? (
            <Skeleton className="h-20 w-full" />
          ) : (
            <div className="max-h-56 space-y-1 overflow-y-auto pr-1 text-sm">
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={lawFilter.length === 0} onChange={() => setLawFilter([])} />
                {t("ask.allLaws")}
              </label>
              {laws.map((l) => (
                <label key={l.law_id} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={lawFilter.includes(l.law_id)}
                    onChange={(e) =>
                      setLawFilter((f) => (e.target.checked ? [...f, l.law_id] : f.filter((x) => x !== l.law_id)))
                    }
                  />
                  <span className="truncate" title={l.title}>
                    {l.title}
                  </span>
                </label>
              ))}
            </div>
          )}
        </Card>

        {retrieval?.subgraph && retrieval.subgraph.nodes.length > 0 && (
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">{t("ask.graphView")}</h3>
            <GraphView
              graph={retrieval.subgraph}
              height={320}
              onNodeClick={(id, kind) =>
                kind === "Article" && (window.location.href = `/articles/view/?uid=${encodeURIComponent(id)}`)
              }
            />
          </div>
        )}

        {retrieval && (
          <Card className="p-4">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">{t("ask.timings")}</h3>
            <dl className="grid grid-cols-2 gap-y-1 font-mono text-xs">
              {Object.entries(retrieval.timings_ms).map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="text-muted">{k}</dt>
                  <dd className="text-right">{v}</dd>
                </div>
              ))}
            </dl>
          </Card>
        )}
      </aside>
    </div>
  );
}
