"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { I18nProvider, useT } from "@/lib/i18n";
import { cx } from "./ui";

export function Logo({ className }: { className?: string }) {
  // Con dấu (hanko) vuông + 3 node nối nhau: "điều luật" được liên kết thành graph
  return (
    <svg viewBox="0 0 32 32" fill="none" aria-label="JP Legal GraphRAG" className={className}>
      <rect x="2.5" y="2.5" width="27" height="27" rx="5" stroke="currentColor" strokeWidth="2" />
      <path d="M10 11.5 L21.5 10 M10 11.5 L16 21.5 M21.5 10 L16 21.5" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="10" cy="11.5" r="2.6" fill="currentColor" />
      <circle cx="21.5" cy="10" r="2.6" fill="currentColor" />
      <circle cx="16" cy="21.5" r="3.2" fill="var(--shu)" />
    </svg>
  );
}

function StatusDot() {
  const [st, setSt] = useState<"ok" | "warn" | "down" | "loading">("loading");
  const [detail, setDetail] = useState("");
  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .status()
        .then((s) => {
          if (!alive) return;
          const bad = Object.entries(s).filter(([k, v]) => k !== "llm" && !v.ok);
          setSt(bad.length ? "warn" : "ok");
          setDetail(
            Object.entries(s)
              .map(([k, v]) => `${k}: ${v.ok ? "OK" : (v.error ?? "—")}`)
              .join("\n"),
          );
        })
        .catch((e) => alive && (setSt("down"), setDetail(String(e))));
    load();
    const id = setInterval(load, 30000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);
  const color = { ok: "bg-ok", warn: "bg-kin", down: "bg-bad", loading: "bg-line" }[st];
  return (
    <span title={detail} className="hidden items-center gap-1.5 text-xs text-muted sm:flex">
      <span className={cx("h-2 w-2 rounded-full", color)} />
      API
    </span>
  );
}

function Nav() {
  const { t, lang, setLang } = useT();
  const path = usePathname();
  const items = [
    { href: "/", label: t("nav.ask") },
    { href: "/ingest/", label: t("nav.ingest") },
    { href: "/jobs/", label: t("nav.jobs") },
    { href: "/laws/", label: t("nav.laws") },
  ];
  const active = (h: string) => (h === "/" ? path === "/" : path.startsWith(h.replace(/\/$/, "")));
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-paper/90 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-7xl items-center gap-3 px-4 sm:gap-6 sm:px-6">
        <Link href="/" className="flex shrink-0 items-center gap-2.5 text-ai">
          <Logo className="h-7 w-7" />
          <span className="hidden text-sm font-semibold text-ink sm:inline">
            JP Legal <span className="text-muted font-normal">GraphRAG</span>
          </span>
        </Link>
        <nav className="flex min-w-0 items-center gap-1 overflow-x-auto [scrollbar-width:none]">
          {items.map((i) => (
            <Link
              key={i.href}
              href={i.href}
              className={cx(
                "whitespace-nowrap rounded-md px-3 py-1.5 text-sm transition-colors",
                active(i.href) ? "bg-surface-2 font-medium text-ink" : "text-muted hover:text-ink",
              )}
            >
              {i.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex shrink-0 items-center gap-4">
          <StatusDot />
          <div className="flex overflow-hidden rounded-md border border-line text-xs">
            {(["vi", "ja"] as const).map((l) => (
              <button
                key={l}
                onClick={() => setLang(l)}
                className={cx("whitespace-nowrap px-2.5 py-1", lang === l ? "bg-ink text-paper" : "text-muted hover:bg-surface-2")}
              >
                {l === "vi" ? "VI" : "JA"}
              </button>
            ))}
          </div>
        </div>
      </div>
    </header>
  );
}

function Footer() {
  const { t } = useT();
  return (
    <footer className="mx-auto max-w-7xl px-4 py-8 text-xs text-muted sm:px-6">{t("footer.source")}</footer>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  return (
    <I18nProvider>
      <Nav />
      <main className="mx-auto min-h-[calc(100vh-9rem)] max-w-7xl px-4 py-6 sm:px-6">{children}</main>
      <Footer />
    </I18nProvider>
  );
}
