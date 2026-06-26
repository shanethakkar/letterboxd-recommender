import { API_BASE, ApiError } from "./api";
import type { GraphPayload } from "./types";

export type Phase = "scraping" | "enriching" | "scoring" | "embedding";

export interface PhaseEvent {
  phase: Phase;
  progress?: number;
  detail?: string;
}

/** A film streamed in during enrichment — enough to cascade its poster into the cloud. */
export interface CascadeNode {
  id: string;
  title: string;
  year: number | null;
  poster_url: string | null;
  rating: number | null;
}

interface StreamOpts {
  refresh?: boolean;
  onPhase?: (p: PhaseEvent) => void;
  onNodes?: (nodes: CascadeNode[], progress?: number) => void;
  signal?: AbortSignal;
}

/**
 * Consume the build SSE stream (`GET /api/graph/{username}/stream`), surfacing `phase` + `nodes`
 * (the poster cascade) as they arrive and resolving with the final payload on `result`. Uses
 * fetch + ReadableStream (not EventSource) so it's abortable and never auto-reconnects — a
 * reconnect would restart the multi-minute build.
 */
export async function streamGraph(username: string, opts: StreamOpts = {}): Promise<GraphPayload> {
  const url = new URL(`${API_BASE}/api/graph/${encodeURIComponent(username)}/stream`);
  if (opts.refresh) url.searchParams.set("refresh", "true");

  let resp: Response;
  try {
    resp = await fetch(url.toString(), {
      headers: { Accept: "text/event-stream" },
      signal: opts.signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "Couldn't reach the recommender — is the backend running?");
  }
  if (!resp.ok || !resp.body) {
    throw new ApiError(resp.status || 0, `Stream failed (${resp.status}).`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const boundary = /\r\n\r\n|\n\n|\r\r/; // SSE events are separated by a blank line (any EOL style)

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let m: RegExpExecArray | null;
      while ((m = boundary.exec(buffer))) {
        const raw = buffer.slice(0, m.index);
        buffer = buffer.slice(m.index + m[0].length);
        const evt = parseEvent(raw);
        if (!evt) continue;

        if (evt.event === "phase") {
          opts.onPhase?.(evt.data as PhaseEvent);
        } else if (evt.event === "nodes") {
          const d = evt.data as { nodes: CascadeNode[]; progress?: number };
          opts.onNodes?.(d.nodes, d.progress);
        } else if (evt.event === "result") {
          return evt.data as GraphPayload;
        } else if (evt.event === "error") {
          const d = evt.data as { status?: number; detail?: string };
          throw new ApiError(d.status ?? 0, d.detail ?? "Something went wrong building the map.");
        }
      }
    }
  } finally {
    reader.cancel().catch(() => {});
  }

  throw new ApiError(0, "The stream ended before the map was ready.");
}

function parseEvent(raw: string): { event: string; data: unknown } | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of raw.split(/\r\n|\r|\n/)) {
    if (!line || line.startsWith(":")) continue; // blank / heartbeat / comment
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
  }
  if (dataLines.length === 0) return null;
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    return null;
  }
}
