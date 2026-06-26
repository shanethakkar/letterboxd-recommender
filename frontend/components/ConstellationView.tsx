"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, fetchGraph } from "@/lib/api";
import type { GraphNode, GraphPayload } from "@/lib/types";
import { hasWebGL } from "@/lib/webgl";
import DetailPanel from "./DetailPanel";
import Filters, { type FilterState } from "./Filters";
import RankedList from "./RankedList";

const Constellation = dynamic(() => import("./Constellation"), { ssr: false });

const ALL_VISIBLE: FilterState = {
  showWatched: true,
  showRecommended: true,
  cluster: null,
  genre: null,
};

export default function ConstellationView({ username }: { username: string }) {
  const [payload, setPayload] = useState<GraphPayload | null>(null);
  const [error, setError] = useState<{ status: number; message: string } | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filters, setFilters] = useState<FilterState>(ALL_VISIBLE);
  const [webgl, setWebgl] = useState(true);

  // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time client capability probe
  useEffect(() => setWebgl(hasWebGL()), []);

  // The route remounts this component per username (key={username}), so initial state is
  // already fresh here — the effect only kicks off the async fetch.
  useEffect(() => {
    let cancelled = false;
    fetchGraph(username)
      .then((p) => !cancelled && setPayload(p))
      .catch(
        (e) =>
          !cancelled &&
          setError({ status: e instanceof ApiError ? e.status : 0, message: String(e.message) }),
      );
    return () => {
      cancelled = true;
    };
  }, [username]);

  const visible = useCallback(
    (n: GraphNode) =>
      (n.type === "watched" ? filters.showWatched : filters.showRecommended) &&
      (filters.cluster === null || n.cluster === filters.cluster) &&
      (filters.genre === null || n.genres.includes(filters.genre)),
    [filters],
  );

  const genres = useMemo(() => {
    if (!payload) return [];
    return Array.from(new Set(payload.nodes.flatMap((n) => n.genres))).sort();
  }, [payload]);

  if (error) return <ErrorScreen username={username} error={error} />;
  if (!payload) return <LoadingScreen username={username} />;
  if (!webgl) return <RankedList payload={payload} />;

  const selectedNode = selectedId
    ? payload.nodes.find((n) => n.id === selectedId) ?? null
    : null;
  const selectedRec =
    selectedNode?.type === "recommended"
      ? payload.recommendations.find((r) => r.id === selectedId) ?? null
      : null;

  return (
    <main className="atmosphere relative h-screen w-screen overflow-hidden">
      <Constellation
        payload={payload}
        selectedId={selectedId}
        onSelect={setSelectedId}
        visible={visible}
      />
      <Header payload={payload} />
      <Filters
        clusters={payload.clusters}
        genres={genres}
        state={filters}
        setState={setFilters}
      />
      <Legend />
      {selectedNode && (
        <DetailPanel
          node={selectedNode}
          recommendation={selectedRec}
          onClose={() => setSelectedId(null)}
          onSelectSeed={setSelectedId}
        />
      )}
    </main>
  );
}

function Header({ payload }: { payload: GraphPayload }) {
  const [copied, setCopied] = useState(false);
  const share = () => {
    navigator.clipboard?.writeText(window.location.href).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    });
  };
  const { rated, avg_rating, clusters } = payload.stats;
  return (
    <header className="pointer-events-auto absolute left-4 top-4 z-20 flex items-center gap-4">
      <Link
        href="/"
        className="font-display text-sm text-dim transition hover:text-leader"
        aria-label="Home"
      >
        ←
      </Link>
      <div>
        <h1 className="font-display text-base font-semibold leading-none text-leader">
          @{payload.username}
        </h1>
        <p className="mt-1 font-mono text-[11px] text-dim">
          {rated} rated · avg {avg_rating.toFixed(2)} · {clusters} clusters
        </p>
      </div>
      <button
        onClick={share}
        className="ml-2 rounded-full border border-white/10 bg-panel/70 px-3 py-1.5 font-mono text-[11px] text-dim backdrop-blur transition hover:border-beam/40 hover:text-leader"
      >
        {copied ? "copied ✓" : "share"}
      </button>
    </header>
  );
}

function Legend() {
  return (
    <div className="pointer-events-none absolute bottom-4 left-4 z-20 flex flex-col gap-1 font-mono text-[10px] text-dim">
      <span>
        <span className="text-leader">●</span> watched · sized by your rating
      </span>
      <span>
        <span className="text-beam">●</span> recommended · sized by match
      </span>
      <span>
        <span className="text-beam">—</span> why: the films that earned a rec
      </span>
    </div>
  );
}

function LoadingScreen({ username }: { username: string }) {
  return (
    <main
      aria-live="polite"
      aria-busy="true"
      className="atmosphere flex min-h-screen flex-col items-center justify-center gap-3 px-6 text-center"
    >
      <div
        aria-hidden
        className="h-6 w-6 animate-spin rounded-full border-2 border-white/15 border-t-beam"
      />
      <p className="font-display text-lg text-leader">Mapping @{username}…</p>
      <p className="max-w-sm font-mono text-xs text-dim">
        Reading the diary, enriching films, scoring taste. A first map can take a couple of
        minutes; after that it&apos;s instant.
      </p>
    </main>
  );
}

function ErrorScreen({
  username,
  error,
}: {
  username: string;
  error: { status: number; message: string };
}) {
  return (
    <main
      role="alert"
      className="atmosphere flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center"
    >
      <p className="font-mono text-[11px] uppercase tracking-[0.3em] text-dim">
        @{username}
      </p>
      <p className="max-w-md font-display text-xl leading-snug text-leader">{error.message}</p>
      <Link
        href="/"
        className="rounded-full bg-leader px-5 py-2 font-display text-sm text-void transition hover:bg-beam"
      >
        Try another username
      </Link>
    </main>
  );
}
