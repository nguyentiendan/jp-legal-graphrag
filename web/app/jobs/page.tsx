"use client";

import { Fragment, useEffect, useState } from "react";
import { Card, Empty, ErrorBox, Progress, Skeleton, StatusPill } from "@/components/ui";
import { api, type Job } from "@/lib/api";
import { useT } from "@/lib/i18n";

function target(j: Job): string {
  const p = j.params as Record<string, unknown>;
  if (j.filename) return j.filename;
  if (Array.isArray(p.law_ids) && p.law_ids.length) return (p.law_ids as string[]).join(", ");
  if (p.zip_path) return String(p.zip_path);
  if (p.update_date) return `update ${p.update_date}`;
  return "—";
}

function fmt(d: string | null) {
  return d ? new Date(d).toLocaleString() : "—";
}

export default function JobsPage() {
  const { t } = useT();
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .jobs()
        .then((j) => alive && (setJobs(j), setError(null)))
        .catch((e) => alive && setError(String(e)));
    load();
    const id = setInterval(load, 3000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  return (
    <div>
      <h1 className="mb-5 text-xl font-semibold">{t("jobs.title")}</h1>
      {error && <ErrorBox message={error} />}
      {jobs === null && !error && <Skeleton className="h-40 w-full" />}
      {jobs?.length === 0 && <Empty>{t("jobs.empty")}</Empty>}
      {jobs && jobs.length > 0 && (
        <Card className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs text-muted">
                <th className="px-4 py-2.5 font-medium">ID</th>
                <th className="px-4 py-2.5 font-medium">{t("jobs.kind")}</th>
                <th className="px-4 py-2.5 font-medium">{t("jobs.target")}</th>
                <th className="px-4 py-2.5 font-medium">{t("jobs.status")}</th>
                <th className="w-64 px-4 py-2.5 font-medium">{t("jobs.progress")}</th>
                <th className="px-4 py-2.5 font-medium">{t("jobs.created")}</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <Fragment key={j.id}>
                  <tr
                    onClick={() => setOpen(open === j.id ? null : j.id)}
                    className="cursor-pointer border-b border-line last:border-0 hover:bg-surface-2/60"
                  >
                    <td className="px-4 py-3 font-mono text-xs">{j.id.slice(0, 8)}</td>
                    <td className="px-4 py-3">{j.kind}</td>
                    <td className="max-w-[260px] truncate px-4 py-3" title={target(j)}>
                      {target(j)}
                    </td>
                    <td className="px-4 py-3">
                      <StatusPill status={j.status} />
                    </td>
                    <td className="px-4 py-3">
                      <Progress value={j.progress} />
                      <div className="mt-1 truncate text-xs text-muted" title={j.message}>
                        {j.progress}% · {j.message}
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-xs text-muted">{fmt(j.created_at)}</td>
                  </tr>
                  {open === j.id && (
                    <tr className="border-b border-line bg-surface-2/40">
                      <td colSpan={6} className="px-4 py-3">
                        <pre className="max-h-80 overflow-auto whitespace-pre-wrap font-mono text-xs">
                          {JSON.stringify({ params: j.params, result: j.result, error: j.error }, null, 2)}
                        </pre>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
