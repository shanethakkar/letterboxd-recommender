import type { GraphPayload } from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

/** Fetch the constellation payload for a username, surfacing the backend's typed errors. */
export async function fetchGraph(
  username: string,
  opts: { refresh?: boolean } = {},
): Promise<GraphPayload> {
  const url = new URL(`${API_BASE}/api/graph/${encodeURIComponent(username)}`);
  if (opts.refresh) url.searchParams.set("refresh", "true");

  let resp: Response;
  try {
    resp = await fetch(url.toString(), { cache: "no-store" });
  } catch {
    throw new ApiError(0, "Couldn't reach the recommender — is the backend running?");
  }

  if (!resp.ok) {
    let detail = `Request failed (${resp.status}).`;
    try {
      const body = await resp.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* non-JSON error body — keep the default */
    }
    throw new ApiError(resp.status, detail);
  }
  return (await resp.json()) as GraphPayload;
}
