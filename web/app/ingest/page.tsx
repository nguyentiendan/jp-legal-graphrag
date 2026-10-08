"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { Button, Card, cx, ErrorBox, Input, Label, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";

type Tab = "upload" | "egov" | "bulk";

function Notice({ jobId, extra }: { jobId: string; extra?: string }) {
  const { t } = useT();
  return (
    <div className="rounded-md border border-ok/30 bg-[color-mix(in_srgb,var(--ok)_8%,transparent)] px-4 py-3 text-sm">
      {t("ingest.queued")}:{" "}
      <Link href="/jobs/" className="font-mono text-ai underline">
        {jobId.slice(0, 8)}
      </Link>
      {extra && <span className="ml-2 text-muted">{extra}</span>}
    </div>
  );
}

function UploadTab() {
  const { t } = useT();
  const [files, setFiles] = useState<File[]>([]);
  const [title, setTitle] = useState("");
  const [force, setForce] = useState(false);
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState(false);
  const [results, setResults] = useState<{ name: string; msg: string; jobId?: string }[]>([]);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    const out: typeof results = [];
    for (const f of files) {
      try {
        const r = await api.upload(f, files.length === 1 ? title || undefined : undefined, force);
        out.push({ name: f.name, msg: r.duplicate ? t("ingest.duplicate") : t("ingest.queued"), jobId: r.job_id ?? undefined });
      } catch (e) {
        out.push({ name: f.name, msg: String(e) });
      }
    }
    setResults(out);
    setFiles([]);
    setBusy(false);
  };

  return (
    <div className="space-y-4">
      <div
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          setFiles(Array.from(e.dataTransfer.files));
        }}
        className={cx(
          "flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-6 py-12 text-center transition-colors",
          drag ? "border-ai bg-ai-soft" : "border-line hover:border-muted",
        )}
      >
        <svg viewBox="0 0 24 24" className="mb-3 h-8 w-8 text-muted" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M12 16V4m0 0-4 4m4-4 4 4M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
        </svg>
        <p className="text-sm font-medium">{t("ingest.drop")}</p>
        <p className="mt-1 text-xs text-muted">{t("ingest.formats")}</p>
        <input
          ref={input}
          type="file"
          multiple
          accept=".xml,.pdf,.docx,.txt,.md"
          className="hidden"
          onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
        />
      </div>
      {files.length > 0 && (
        <ul className="space-y-1 text-sm">
          {files.map((f) => (
            <li key={f.name} className="flex justify-between rounded bg-surface-2 px-3 py-1.5">
              <span className="truncate">{f.name}</span>
              <span className="text-muted">{(f.size / 1024).toFixed(0)} KB</span>
            </li>
          ))}
        </ul>
      )}
      {files.length <= 1 && (
        <div>
          <Label>{t("ingest.title")}</Label>
          <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="例：就業規則（2026年版）" />
        </div>
      )}
      <label className="flex items-center gap-2 text-sm text-muted">
        <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
        {t("ingest.force")}
      </label>
      <Button onClick={submit} disabled={!files.length || busy}>
        {t("ingest.start")}
      </Button>
      {error && <ErrorBox message={error} />}
      {results.length > 0 && (
        <ul className="space-y-1 text-sm">
          {results.map((r) => (
            <li key={r.name} className="flex flex-wrap gap-2">
              <span className="font-medium">{r.name}</span>
              <span className="text-muted">{r.msg}</span>
              {r.jobId && (
                <Link href="/jobs/" className="font-mono text-ai underline">
                  {r.jobId.slice(0, 8)}
                </Link>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const lines = (s: string) =>
  s
    .split(/[\n,]/)
    .map((x) => x.trim())
    .filter(Boolean);

function EgovTab() {
  const { t } = useT();
  const [ids, setIds] = useState("322AC0000000049\n322M40000100023\n419AC0000000128");
  const [titles, setTitles] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<{ job_id: string; unresolved_titles: string[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      setRes(await api.ingestEgov({ law_ids: lines(ids), titles: lines(titles) }));
    } catch (e) {
      setError(String(e));
    }
    setBusy(false);
  };
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">{t("ingest.egovNote")}</p>
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <Label>{t("ingest.lawIds")}</Label>
          <Textarea rows={6} value={ids} onChange={(e) => setIds(e.target.value)} className="font-mono" />
        </div>
        <div>
          <Label>{t("ingest.titles")}</Label>
          <Textarea rows={6} value={titles} onChange={(e) => setTitles(e.target.value)} placeholder={"労働安全衛生法\n最低賃金法"} />
        </div>
      </div>
      <Button onClick={submit} disabled={busy || (!lines(ids).length && !lines(titles).length)}>
        {t("ingest.start")}
      </Button>
      {error && <ErrorBox message={error} />}
      {res && <Notice jobId={res.job_id} extra={res.unresolved_titles.length ? `✗ ${res.unresolved_titles.join("、")}` : ""} />}
    </div>
  );
}

function BulkTab() {
  const { t } = useT();
  const [zip, setZip] = useState("/data/import/all.zip");
  const [cat, setCat] = useState("");
  const [ids, setIds] = useState("");
  const [contains, setContains] = useState("");
  const [max, setMax] = useState(200);
  const [busy, setBusy] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.ingestBulk({
        zip_path: cat ? null : zip || null,
        category_cd: cat ? Number(cat) : null,
        law_ids: lines(ids),
        title_contains: contains || null,
        max_laws: max,
      });
      setJobId(r.job_id);
    } catch (e) {
      setError(String(e));
    }
    setBusy(false);
  };
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">{t("ingest.bulkNote")}</p>
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <Label>{t("ingest.zipPath")}</Label>
          <Input value={zip} onChange={(e) => setZip(e.target.value)} className="font-mono" />
        </div>
        <div>
          <Label>{t("ingest.categoryCd")}</Label>
          <Input value={cat} onChange={(e) => setCat(e.target.value.replace(/\D/g, ""))} placeholder="例：37" />
        </div>
        <div>
          <Label>{t("ingest.filterIds")}</Label>
          <Textarea rows={3} value={ids} onChange={(e) => setIds(e.target.value)} className="font-mono" />
        </div>
        <div className="space-y-4">
          <div>
            <Label>{t("ingest.titleContains")}</Label>
            <Input value={contains} onChange={(e) => setContains(e.target.value)} placeholder="労働" />
          </div>
          <div>
            <Label>{t("ingest.maxLaws")}</Label>
            <Input type="number" min={1} max={10000} value={max} onChange={(e) => setMax(Number(e.target.value))} />
          </div>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button onClick={submit} disabled={busy}>
          {t("ingest.start")}
        </Button>
        <Button
          variant="outline"
          onClick={async () => {
            try {
              setJobId((await api.rebuildLinks()).job_id);
            } catch (e) {
              setError(String(e));
            }
          }}
        >
          {t("ingest.rebuild")}
        </Button>
      </div>
      {error && <ErrorBox message={error} />}
      {jobId && <Notice jobId={jobId} />}
    </div>
  );
}

export default function IngestPage() {
  const { t } = useT();
  const [tab, setTab] = useState<Tab>("upload");
  const tabs: { id: Tab; label: string }[] = [
    { id: "upload", label: t("ingest.upload") },
    { id: "egov", label: t("ingest.egov") },
    { id: "bulk", label: t("ingest.bulk") },
  ];
  return (
    <div className="mx-auto max-w-4xl">
      <h1 className="mb-5 text-xl font-semibold">{t("nav.ingest")}</h1>
      <div className="mb-4 flex gap-1 overflow-x-auto border-b border-line [scrollbar-width:none]">
        {tabs.map((x) => (
          <button
            key={x.id}
            onClick={() => setTab(x.id)}
            className={cx(
              "-mb-px whitespace-nowrap border-b-2 px-4 py-2 text-sm",
              tab === x.id ? "border-ai font-medium text-ink" : "border-transparent text-muted hover:text-ink",
            )}
          >
            {x.label}
          </button>
        ))}
      </div>
      <Card className="p-5">{tab === "upload" ? <UploadTab /> : tab === "egov" ? <EgovTab /> : <BulkTab />}</Card>
    </div>
  );
}
