"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError } from "@/lib/api";
import { streamGraph, type CascadeNode, type Phase, type PhaseEvent } from "@/lib/stream";
import type { GraphNode, GraphPayload } from "@/lib/types";
import { hasWebGL } from "@/lib/webgl";
import DetailPanel from "./DetailPanel";
import Filters, { type FilterState } from "./Filters";
import GlassBackground from "./GlassBackground";
import RecommendationsConsole from "./RecommendationsConsole";
import RecRail from "./RecRail";

const Constellation = dynamic(() => import("./Constellation"), { ssr: false });
const RevealStream = dynamic(() => import("./RevealStream"), { ssr: false });

const ALL_VISIBLE: FilterState = {
  showWatched: true,
  showRecommended: true,
  cluster: null,
  genre: null,
};

// reveal (live cascade → crystallize) → glass ↔ explore
type Mode = "reveal" | "glass" | "explore";

const RECEDE_MS = 900; // matches .constellation-recede

const PHASE_STEPS: { key: Phase; label: string }[] = [
  { key: "scraping", label: "Reading the diary" },
  { key: "enriching", label: "Enriching films" },
  { key: "scoring", label: "Scoring your taste" },
  { key: "embedding", label: "Mapping the constellation" },
];

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
  const [recedeCanvas, setRecedeCanvas] = useState(false);
  const [phase, setPhase] = useState<PhaseEvent | null>(null);
  const [cloud, setCloud] = useState<CascadeNode[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focusId, setFocusId] = useState<string | null>(null);
  const [filters, setFilters] = useState<FilterState>(ALL_VISIBLE);
  const [webgl, setWebgl] = useState(true);

  // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time client capability probe
  useEffect(() => setWebgl(hasWebGL()), []);

  // Stream the build: phases + the poster cascade arrive live; the payload resolves at the end.
  useEffect(() => {
    const ctrl = new AbortController();
    streamGraph(username, {
      signal: ctrl.signal,
      onPhase: setPhase,
      onNodes: (nodes) => setCloud((c) => [...c, ...nodes]),
    })
      .then(setPayload)
      .catch((e) => {
        if ((e as Error).name === "AbortError") return;
        setError({
          status: e instanceof ApiError ? e.status : 0,
          message: String((e as Error).message),
        });
      });
    return () => ctrl.abort();
  }, [username]);

  // Once the map crystallizes, recede it and hand off to the glass console.
  const handoff = useCallback(() => {
    setMode("glass");
    if (reducedMotion()) return;
    setRecedeCanvas(true);
    window.setTimeout(() => setRecedeCanvas(false), RECEDE_MS);
  }, []);

  useEffect(() => {
    if (!payload || mode !== "reveal" || !webgl) return;
    const t = setTimeout(handoff, reducedMotion() ? 400 : 2400); // let the crystallization play
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

  // No WebGL: skip the cascade reveal — a phase-aware spinner, then straight to the glass console.
  if (!webgl) {
    if (!payload) return <LoadingScreen username={username} phase={phase} />;
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
      ? payload?.recommendations.find((r) => r.id === selectedId) ?? null
      : null;

  const mainClass =
    mode === "glass"
      ? "atmosphere relative min-h-screen overflow-x-hidden"
      : "atmosphere relative h-screen w-screen overflow-hidden";

  return (
    <main className={mainClass}>
      {/* Receded constellation (glass background) — present once we hand off. */}
      {mode === "glass" && <GlassBackground key="glass-bg" posters={posters} />}

      {/* The live reveal: posters cascade in during the build, then crystallize. Same element
          across reveal→recede (keyed) so it never remounts. */}
      {showRevealCanvas && (
        <div
          key="reveal-canvas"
          className={`fixed inset-0 z-[5] ${
            mode === "glass" && recedeCanvas ? "constellation-recede" : ""
          }`}
        >
          <RevealStream cloud={cloud} payload={payload} reducedMotion={reducedMotion()} />
        </div>
      )}

      {/* Live pipeline intro. */}
      {mode === "reveal" && <PhaseIntro phase={phase} crystallizing={!!payload} />}

      {/* The recommendations, on glass. */}
      {mode === "glass" && payload && (
        <RecommendationsConsole
          key="console"
          payload={payload}
          canExplore
          onExplore={() => setMode("explore")}
        />
      )}

      {/* Explore: the live, interactive map brought forward. */}
      {mode === "explore" && payload && (
        <div key="explore" className="absolute inset-0">
          <Constellation
            payload={payload}
            animate={false}
            variant="dots"
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

function PhaseIntro({ phase, crystallizing }: { phase: PhaseEvent | null; crystallizing: boolean }) {
  const activeIdx = phase ? PHASE_STEPS.findIndex((s) => s.key === phase.phase) : 0;
  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-10 z-20 flex flex-col items-center gap-3">
      <ul className="flex flex-col gap-1.5 rounded-2xl border border-white/10 bg-void/55 px-5 py-4 backdrop-blur-md">
        {PHASE_STEPS.map((s, i) => {
          const done = crystallizing || i < activeIdx;
          const active = !crystallizing && i === activeIdx;
          return (
            <li key={s.key} className="flex items-center gap-3 font-mono text-[11px]">
              <span
                className={
                  done ? "text-beam" : active ? "text-leader" : "text-dim/50"
                }
              >
                {done ? "✓" : active ? "◆" : "○"}
              </span>
              <span
                className={
                  done ? "text-dim" : active ? "text-leader" : "text-dim/50"
                }
              >
                {s.label}
              </span>
              {active && phase?.detail && (
                <span className="text-dim">· {phase.detail}</span>
              )}
            </li>
          );
        })}
      </ul>
      <p className="font-mono text-[10px] uppercase tracking-[0.35em] text-dim">
        {crystallizing ? "crystallising your taste" : "watching it think"}
      </p>
    </div>
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
        <span className="text-dim">●</span> colour = a region of your taste · hover for the poster
      </span>
      <span>
        <span className="text-beam">—</span> why: a rec → the films behind it
      </span>
    </div>
  );
}

function LoadingScreen({ username, phase }: { username: string; phase: PhaseEvent | null }) {
  const label = phase
    ? PHASE_STEPS.find((s) => s.key === phase.phase)?.label ?? "Mapping"
    : "Mapping";
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
      <p className="font-display text-lg text-leader">
        {label} @{username}…
      </p>
      <p className="max-w-sm font-mono text-xs text-dim">
        {phase?.detail ? `${phase.detail} · ` : ""}A first map can take a couple of minutes; after
        that it&apos;s instant.
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
