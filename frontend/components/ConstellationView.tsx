"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, fetchGraph } from "@/lib/api";
import type { GraphNode, GraphPayload } from "@/lib/types";
import { hasWebGL } from "@/lib/webgl";
import DetailPanel from "./DetailPanel";
import Filters, { type FilterState } from "./Filters";
import GlassBackground from "./GlassBackground";
import RecommendationsConsole from "./RecommendationsConsole";
import RecRail from "./RecRail";

const Constellation = dynamic(() => import("./Constellation"), { ssr: false });

const ALL_VISIBLE: FilterState = {
  showWatched: true,
  showRecommended: true,
  cluster: null,
  genre: null,
};

// reveal → (recede) → glass ↔ explore
type Mode = "reveal" | "glass" | "explore";

const REVEAL_MS = 2800; // crystallize, then hand off to the glass console
const RECEDE_MS = 900; // the live canvas blurs out, then unmounts (matches .constellation-recede)

function reducedMotion() {
  return (
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
  );
}

export default function ConstellationView({ username }: { username: string }) {
  const [payload, setPayload] = useState<GraphPayload | null>(null);
  const [error, setError] = useState<{ status: number; message: string } | null>(null);
  const [mode, setMode] = useState<Mode>("reveal");
  const [recedeCanvas, setRecedeCanvas] = useState(false); // live canvas still mounted, blurring out
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focusId, setFocusId] = useState<string | null>(null);
  const [filters, setFilters] = useState<FilterState>(ALL_VISIBLE);
  const [webgl, setWebgl] = useState(true);

  // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time client capability probe
  useEffect(() => setWebgl(hasWebGL()), []);

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

  // Reveal → glass: the crystallized map recedes (blurs out) while the glass console
  // rises over it; once the recede finishes we unmount the WebGL canvas so the steady
  // state is just the cheap static bokeh + glass (no live WebGL behind backdrop-filter).
  const handoff = useCallback(() => {
    setMode("glass");
    if (reducedMotion()) return; // no recede; the reveal canvas simply isn't rendered in glass
    setRecedeCanvas(true);
    window.setTimeout(() => setRecedeCanvas(false), RECEDE_MS);
  }, []);

  useEffect(() => {
    if (!payload || mode !== "reveal" || !webgl) return;
    const t = setTimeout(handoff, reducedMotion() ? 500 : REVEAL_MS);
    return () => clearTimeout(t);
  }, [payload, mode, webgl, handoff]);

  const visible = useCallback(
    (n: GraphNode) =>
      (n.type === "watched" ? filters.showWatched : filters.showRecommended) &&
      (filters.cluster === null || n.cluster === filters.cluster) &&
      (filters.genre === null || n.genres.includes(filters.genre)),
    [filters],
  );

  const genres = useMemo(
    () => Array.from(new Set((payload?.nodes ?? []).flatMap((n) => n.genres))).sort(),
    [payload],
  );

  // Recs come first in the node list, so this is recs-then-seeds — the brightest
  // posters land in the bokeh field.
  const posters = useMemo(
    () => (payload?.nodes ?? []).map((n) => n.poster_url).filter((u): u is string => !!u),
    [payload],
  );

  const nodeById = useMemo(() => {
    const m = new Map<string, GraphNode>();
    for (const n of payload?.nodes ?? []) m.set(n.id, n);
    return m;
  }, [payload]);

  const selectFromRail = useCallback((id: string) => {
    setSelectedId(id);
    setFocusId(id);
  }, []);

  if (error) return <ErrorScreen username={username} error={error} />;
  if (!payload) return <LoadingScreen username={username} />;

  // No WebGL: skip the reveal entirely — straight to the glass console (pure CSS,
  // so it still looks the part), with no "explore" option.
  if (!webgl) {
    return (
      <main className="atmosphere relative min-h-screen overflow-hidden">
        <RecommendationsConsole payload={payload} canExplore={false} onExplore={() => {}} />
      </main>
    );
  }

  const showRevealCanvas = mode === "reveal" || (mode === "glass" && recedeCanvas);

  const selectedNode = selectedId ? nodeById.get(selectedId) ?? null : null;
  const selectedRec =
    selectedNode?.type === "recommended"
      ? payload.recommendations.find((r) => r.id === selectedId) ?? null
      : null;

  // Glass scrolls (the console is tall); reveal/explore are fixed full-screen.
  const mainClass =
    mode === "glass"
      ? "atmosphere relative min-h-screen overflow-x-hidden"
      : `atmosphere relative h-screen w-screen overflow-hidden${mode === "reveal" ? " cursor-pointer" : ""}`;

  return (
    <main className={mainClass} onClick={mode === "reveal" ? handoff : undefined}>
      {/* Receded constellation (the glass background) — present once we hand off. */}
      {mode === "glass" && <GlassBackground key="glass-bg" posters={posters} />}

      {/* The crystallizing canvas: full-screen in reveal, then blurs out as it recedes.
          Same element across reveal→recede (keyed) so it never remounts/re-crystallizes. */}
      {showRevealCanvas && (
        <div
          key="reveal-canvas"
          className={`fixed inset-0 z-[5] ${
            mode === "glass" && recedeCanvas ? "constellation-recede" : ""
          }`}
        >
          <Constellation
            payload={payload}
            animate
            selectedId={null}
            onSelect={() => {}}
            focusId={null}
            visible={() => true}
          />
        </div>
      )}

      {/* The recommendations, on glass. */}
      {mode === "glass" && (
        <RecommendationsConsole
          key="console"
          payload={payload}
          canExplore
          onExplore={() => setMode("explore")}
        />
      )}

      {/* Reveal caption. */}
      {mode === "reveal" && (
        <div
          key="caption"
          className="pointer-events-none absolute inset-x-0 bottom-10 z-20 text-center"
        >
          <p className="font-mono text-[11px] uppercase tracking-[0.35em] text-dim">
            crystallising your taste
          </p>
          <p className="mt-2 font-mono text-[10px] text-dim/60">tap to skip</p>
        </div>
      )}

      {/* Explore: the live, interactive map brought forward. */}
      {mode === "explore" && (
        <div key="explore" className="absolute inset-0">
          <Constellation
            payload={payload}
            animate={false}
            selectedId={selectedId}
            onSelect={setSelectedId}
            focusId={focusId}
            visible={visible}
          />
          <ExploreHeader payload={payload} onBack={() => setMode("glass")} />
          <Filters
            clusters={payload.clusters}
            genres={genres}
            state={filters}
            setState={setFilters}
          />
          <Legend />
          <RecRail
            recommendations={payload.recommendations}
            nodeById={nodeById}
            selectedId={selectedId}
            onSelect={selectFromRail}
          />
          {selectedNode && (
            <DetailPanel
              node={selectedNode}
              recommendation={selectedRec}
              onClose={() => setSelectedId(null)}
              onSelectSeed={selectFromRail}
            />
          )}
        </div>
      )}
    </main>
  );
}

function ExploreHeader({ payload, onBack }: { payload: GraphPayload; onBack: () => void }) {
  return (
    <header className="pointer-events-auto absolute left-4 top-4 z-30 flex items-center gap-4">
      <button
        onClick={onBack}
        className="rounded-full border border-white/10 bg-panel/70 px-3 py-1.5 font-display text-sm text-leader backdrop-blur transition hover:border-beam/40"
      >
        ← Recommendations
      </button>
      <div>
        <h1 className="font-display text-sm font-semibold leading-none text-leader">
          @{payload.username}
        </h1>
        <p className="mt-1 font-mono text-[11px] text-dim">how the map was built</p>
      </div>
    </header>
  );
}

function Legend() {
  return (
    <div className="pointer-events-none absolute bottom-4 left-4 z-20 flex flex-col gap-1 font-mono text-[10px] text-dim">
      <span>
        <span className="text-beam">◎</span> recommendations · your next watches
      </span>
      <span>
        <span className="text-dim">●</span> the films that earned them
      </span>
      <span>
        <span className="text-beam">—</span> why: a rec → the films behind it
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
      <p className="font-mono text-[11px] uppercase tracking-[0.3em] text-dim">@{username}</p>
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
