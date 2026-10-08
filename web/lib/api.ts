// Client gọi FastAPI qua Nginx (/api). Khi chạy `npm run dev` có thể đặt NEXT_PUBLIC_API_BASE=http://localhost:8000
export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "").replace(/\/$/, "") + "/api";

export type Source = "dense" | "graph";

export interface RetrievedItem {
  uid: string;
  law_id: string;
  law_title: string;
  article_key: string;
  title: string;
  caption: string;
  path: string;
  text: string;
  citation: string;
  sources: Source[];
  dense_rank: number | null;
  dense_score: number | null;
  graph_rank: number | null;
  graph_score: number | null;
  graph_via: { from: string; rel: string; direction: string }[];
  rrf_score: number;
  rerank_score: number | null;
}

export interface GraphNode {
  id: string;
  label: string;
  kind: "Article" | "Law";
  caption?: string;
  seed?: boolean;
  law?: string;
  sources?: Source[];
}
export interface GraphEdge {
  source: string;
  target: string;
  rel: "REFERS_TO" | "APPLIES_MUTATIS_MUTANDIS" | "DELEGATES_TO";
}
export interface Subgraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface RetrievalResult {
  query: string;
  items: RetrievedItem[];
  timings_ms: Record<string, number>;
  subgraph: Subgraph | null;
}

export interface Job {
  id: string;
  kind: string;
  status: "queued" | "running" | "succeeded" | "failed";
  progress: number;
  message: string;
  error: string | null;
  params: Record<string, unknown>;
  result: Record<string, unknown>;
  document_id: string | null;
  filename: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface Law {
  law_id: string;
  title: string;
  abbrev: string;
  law_num: string;
  law_type: string;
  category: string;
  revision_id: string;
  source: string;
  enforcement_date: string;
  num_articles: number;
  num_chunks: number;
  updated_at: string;
}

export interface LawDetail extends Law {
  aliases: Record<string, string>;
  articles: { uid: string; article_key: string; title: string; caption: string; path: string; order: number; degree: number }[];
  unresolved_targets: { name: string; count: number }[];
}

export interface ArticleDetail {
  uid: string;
  law_id: string;
  law_title: string;
  article_key: string;
  title: string;
  caption: string;
  path: string;
  text: string;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, init);
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const j = await r.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* ignore */
    }
    throw new Error(`${r.status} ${detail}`);
  }
  return r.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  status: () => req<Record<string, { ok: boolean; error?: string; model?: string | null }>>("/status"),
  laws: (q?: string) => req<Law[]>(`/laws${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  law: (id: string) => req<LawDetail>(`/laws/${encodeURIComponent(id)}`),
  articleGraph: (uids: string[]) =>
    req<{ articles: ArticleDetail[]; graph: Subgraph }>(
      `/articles/graph?${uids.map((u) => `uid=${encodeURIComponent(u)}`).join("&")}`,
    ),
  stats: () => req<{ neo4j: { laws: number; articles: number; refs: number }; qdrant_points: number }>("/graph/stats"),
  jobs: () => req<Job[]>("/jobs?limit=100"),
  job: (id: string) => req<Job>(`/jobs/${id}`),
  search: (body: AskBody) => req<RetrievalResult>("/search", json(body)),
  ingestEgov: (body: { law_ids: string[]; titles: string[] }) =>
    req<{ job_id: string; law_ids: string[]; unresolved_titles: string[] }>("/ingest/egov", json(body)),
  ingestBulk: (body: Record<string, unknown>) => req<{ job_id: string }>("/ingest/bulk", json(body)),
  rebuildLinks: () => req<{ job_id: string }>("/ingest/rebuild-links", { method: "POST" }),
  upload: (file: File, title?: string, force = false) => {
    const fd = new FormData();
    fd.append("file", file);
    if (title) fd.append("title", title);
    fd.append("force", String(force));
    return req<{ duplicate: boolean; document_id: string; job_id: string | null; law_id?: string }>(
      "/ingest/upload",
      { method: "POST", body: fd },
    );
  },
};

export interface AskBody {
  query: string;
  law_ids?: string[] | null;
  use_graph?: boolean;
  use_rerank?: boolean;
  top_k?: number | null;
}

export interface AskHandlers {
  onRetrieval: (r: RetrievalResult) => void;
  onToken: (t: string) => void;
  onDone: (d: { answer: string; citations: { n: number; uid: string; citation: string; caption: string }[] }) => void;
  onError: (msg: string) => void;
}

/** POST /api/ask – đọc Server-Sent Events từ fetch stream (EventSource không hỗ trợ POST). */
export async function ask(body: AskBody, h: AskHandlers, signal?: AbortSignal): Promise<void> {
  const r = await fetch(`${API_BASE}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
    signal,
  });
  if (!r.ok || !r.body) {
    h.onError(`${r.status} ${r.statusText}`);
    return;
  }
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.search(/\r?\n\r?\n/)) >= 0) {
      const raw = buf.slice(0, idx);
      buf = buf.slice(idx).replace(/^\r?\n\r?\n/, "");
      let event = "message";
      const data: string[] = [];
      for (const line of raw.split(/\r?\n/)) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
      }
      if (!data.length) continue;
      const payload = JSON.parse(data.join("\n"));
      if (event === "retrieval") h.onRetrieval(payload);
      else if (event === "token") h.onToken(payload.t);
      else if (event === "done") h.onDone(payload);
      else if (event === "error") h.onError(payload.message);
    }
  }
}
