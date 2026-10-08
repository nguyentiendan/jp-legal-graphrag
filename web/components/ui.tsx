"use client";

import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from "react";
import { useT } from "@/lib/i18n";
import type { Job, Source } from "@/lib/api";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

export function Button({
  variant = "primary",
  className,
  ...p
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "outline" }) {
  return (
    <button
      {...p}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-md px-4 h-10 text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed",
        variant === "primary" && "bg-ai text-white hover:opacity-90 dark:text-[#10141c]",
        variant === "outline" && "border border-line bg-surface hover:bg-surface-2",
        variant === "ghost" && "hover:bg-surface-2 text-muted hover:text-ink",
        className,
      )}
    />
  );
}

export function Input(p: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...p}
      className={cx(
        "h-10 w-full rounded-md border border-line bg-surface px-3 text-sm placeholder:text-muted/70 focus:border-ai outline-none",
        p.className,
      )}
    />
  );
}

export function Textarea(p: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...p}
      className={cx(
        "w-full rounded-md border border-line bg-surface px-3 py-2 text-sm placeholder:text-muted/70 focus:border-ai outline-none",
        p.className,
      )}
    />
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <section className={cx("rounded-lg border border-line bg-surface", className)}>{children}</section>;
}

export function Label({ children }: { children: ReactNode }) {
  return <label className="mb-1.5 block text-xs font-medium text-muted">{children}</label>;
}

export function SourceBadge({ s }: { s: Source }) {
  const { t } = useT();
  return (
    <span
      className={cx(
        "inline-flex h-5 items-center rounded px-1.5 text-[11px] font-semibold tracking-wide",
        s === "dense" ? "bg-ai-soft text-ai" : "bg-shu-soft text-shu",
      )}
    >
      {t(s === "dense" ? "src.dense" : "src.graph")}
    </span>
  );
}

export function StatusPill({ status }: { status: Job["status"] }) {
  const { t } = useT();
  const cls = {
    queued: "bg-surface-2 text-muted",
    running: "bg-ai-soft text-ai",
    succeeded: "bg-[color-mix(in_srgb,var(--ok)_15%,transparent)] text-ok",
    failed: "bg-[color-mix(in_srgb,var(--bad)_15%,transparent)] text-bad",
  }[status];
  return (
    <span className={cx("inline-flex h-6 items-center rounded-full px-2.5 text-xs font-medium", cls)}>
      {status === "running" && <span className="mr-1.5 h-1.5 w-1.5 animate-pulse rounded-full bg-ai" />}
      {t(`status.${status}`)}
    </span>
  );
}

export function Progress({ value }: { value: number }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
      <div className="h-full rounded-full bg-ai transition-[width] duration-500" style={{ width: `${value}%` }} />
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("animate-pulse rounded bg-surface-2", className)} />;
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  const { t } = useT();
  return (
    <div className="flex items-start justify-between gap-4 rounded-md border border-bad/30 bg-[color-mix(in_srgb,var(--bad)_8%,transparent)] px-4 py-3 text-sm text-bad">
      <span>
        {t("common.error")}: {message}
      </span>
      {onRetry && (
        <button className="shrink-0 underline" onClick={onRetry}>
          {t("common.retry")}
        </button>
      )}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-lg border border-dashed border-line px-6 py-12 text-center text-sm text-muted">{children}</div>;
}
