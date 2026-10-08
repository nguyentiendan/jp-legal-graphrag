"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";

/** Nhãn ngắn trên canvas: "労働基準法施行規則 第二十一条" → "則 第二十一条"; tên đầy đủ hiện ở tooltip */
function shortLabel(label: string, kind?: string): string {
  if (kind === "Law") return label.length > 12 ? label.slice(0, 12) + "…" : label;
  const m = label.match(/^(.*?)\s*(第.+)$/);
  if (!m) return label;
  const law = m[1];
  const tag = law.endsWith("施行規則") ? "則 " : law.endsWith("施行令") ? "令 " : "";
  return tag + m[2];
}
import type { Subgraph } from "@/lib/api";
import { useT } from "@/lib/i18n";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Obj = Record<string, any>;

const REL_VAR: Record<string, string> = {
  REFERS_TO: "--muted",
  APPLIES_MUTATIS_MUTANDIS: "--kin",
  DELEGATES_TO: "--shu",
};

function cssVar(name: string) {
  if (typeof window === "undefined") return "#888";
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
}

export function GraphView({
  graph,
  height = 360,
  onNodeClick,
}: {
  graph: Subgraph;
  height?: number;
  onNodeClick?: (id: string, kind: string) => void;
}) {
  const { t } = useT();
  const wrap = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const fg = useRef<any>(undefined);
  const [width, setWidth] = useState(600);
  const [colors, setColors] = useState<Record<string, string>>({});

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(280, e.contentRect.width)));
    ro.observe(el);
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const read = () =>
      setColors({
        ink: cssVar("--ink"),
        muted: cssVar("--muted"),
        ai: cssVar("--ai"),
        shu: cssVar("--shu"),
        kin: cssVar("--kin"),
        surface: cssVar("--surface"),
        line: cssVar("--line"),
      });
    read();
    mq.addEventListener("change", read);
    return () => {
      ro.disconnect();
      mq.removeEventListener("change", read);
    };
  }, []);

  const data = useMemo(
    () => ({
      nodes: graph.nodes.map((n) => ({ ...n })),
      links: graph.edges.map((e) => ({ ...e })),
    }),
    [graph],
  );

  useEffect(() => {
    const id = setTimeout(() => {
      fg.current?.d3Force("charge")?.strength(-160);
      fg.current?.d3Force("link")?.distance(55);
      fg.current?.d3ReheatSimulation?.();
    }, 50);
    return () => clearTimeout(id);
  }, [data]);

  const relColor = (rel: string) => colors[REL_VAR[rel]?.replace("--", "") ?? "muted"] ?? "#999";

  return (
    <div ref={wrap} className="relative overflow-hidden rounded-md border border-line bg-surface">
      <ForceGraph2D
        ref={fg}
        graphData={data}
        nodeLabel={(n: Obj) => `${n.label}${n.caption ? " " + n.caption : ""}`}
        onEngineStop={() => fg.current?.zoomToFit(300, 30)}
        d3VelocityDecay={0.3}
        width={width}
        height={height}
        backgroundColor="rgba(0,0,0,0)"
        cooldownTicks={80}
        linkDirectionalArrowLength={4}
        linkDirectionalArrowRelPos={0.92}
        linkWidth={1.2}
        linkColor={(l: Obj) => relColor(String(l.rel ?? "REFERS_TO"))}
        nodeRelSize={5}
        onNodeClick={(n: Obj) => onNodeClick?.(String(n.id), String(n.kind ?? "Article"))}
        nodeCanvasObject={(n: Obj, ctx: CanvasRenderingContext2D, scale: number) => {
          const x = n.x ?? 0;
          const y = n.y ?? 0;
          const r = n.kind === "Law" ? 6 : n.seed ? 5.5 : 4;
          const fill =
            n.kind === "Law"
              ? colors.shu
              : n.sources?.length === 1 && n.sources[0] === "graph"
                ? colors.shu
                : n.seed
                  ? colors.ai
                  : colors.muted;
          ctx.beginPath();
          if (n.kind === "Law") ctx.rect(x - r, y - r, r * 2, r * 2);
          else ctx.arc(x, y, r, 0, 2 * Math.PI);
          ctx.fillStyle = fill ?? "#555";
          ctx.fill();
          const fs = Math.max(10 / scale, 2.5);
          if (scale > 1.1 || n.seed) {
            ctx.font = `${fs}px ${getComputedStyle(document.body).fontFamily}`;
            ctx.fillStyle = colors.ink ?? "#222";
            ctx.textAlign = "center";
            ctx.textBaseline = "top";
            ctx.fillText(shortLabel(String(n.label ?? ""), n.kind), x, y + r + 2);
          }
        }}
        nodePointerAreaPaint={(n: Obj, color: string, ctx: CanvasRenderingContext2D) => {
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(n.x ?? 0, n.y ?? 0, 8, 0, 2 * Math.PI);
          ctx.fill();
        }}
      />
      <div className="pointer-events-none absolute bottom-2 left-2 flex flex-wrap gap-3 rounded bg-surface/90 px-2 py-1 text-[11px] text-muted">
        {Object.keys(REL_VAR).map((r) => (
          <span key={r} className="flex items-center gap-1">
            <span className="inline-block h-0.5 w-4" style={{ background: relColor(r) }} />
            {t(`rel.${r}` as "rel.REFERS_TO")}
          </span>
        ))}
      </div>
    </div>
  );
}
