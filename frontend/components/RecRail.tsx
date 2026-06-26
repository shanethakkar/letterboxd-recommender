"use client";

import { useEffect, useState } from "react";

import type { GraphNode, Recommendation } from "@/lib/types";

interface Props {
  recommendations: Recommendation[];
  nodeById: Map<string, GraphNode>;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

function poster(node: GraphNode | undefined): string | null {
  return node?.poster_url ? node.poster_url.replace("/w185/", "/w154/") : null;
}

export default function RecRail({ recommendations, nodeById, selectedId, onSelect }: Props) {
  const [expanded, setExpanded] = useState(false);

  return (
    <>
      <aside className="pointer-events-auto absolute right-0 top-0 z-20 flex h-full w-[19rem] flex-col border-l border-white/10 bg-panel/80 backdrop-blur-md">
        <div className="flex items-center justify-between px-4 pb-3 pt-4">
          <div>
            <h2 className="font-display text-sm font-semibold text-leader">Recommendations</h2>
            <p className="font-mono text-[11px] text-dim">{recommendations.length} films · ranked</p>
          </div>
          <button
            onClick={() => setExpanded(true)}
            aria-label="Expand to full list"
            className="rounded-md border border-white/10 px-2 py-1 font-mono text-[11px] text-dim transition hover:border-beam/40 hover:text-leader"
          >
            list ⤢
          </button>
        </div>
        <ol className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
          {recommendations.map((r, i) => (
            <li key={r.id}>
              <button
                onClick={() => onSelect(r.id)}
                className={`group flex w-full items-center gap-3 rounded-lg p-2 text-left transition ${
                  r.id === selectedId ? "bg-beam/10 ring-1 ring-beam/40" : "hover:bg-white/5"
                }`}
              >
                <span className="w-5 flex-none text-right font-mono text-[11px] text-dim">
                  {i + 1}
                </span>
                {poster(nodeById.get(r.id)) ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={poster(nodeById.get(r.id)) as string}
                    alt=""
                    width={34}
                    height={51}
                    loading="lazy"
                    className="h-[3.2rem] w-[2.1rem] flex-none rounded object-cover ring-1 ring-white/10"
                  />
                ) : (
                  <div className="h-[3.2rem] w-[2.1rem] flex-none rounded bg-white/5" />
                )}
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-leader group-hover:text-beam">
                    {r.title}
                  </span>
                  <span className="font-mono text-[11px] text-dim">
                    {r.year ?? "—"} · <span className="text-beam/90">{r.score.toFixed(2)}</span>
                  </span>
                  {r.shared_traits.length > 0 && (
                    <span className="mt-0.5 block truncate text-[11px] text-dim/80">
                      {r.shared_traits.slice(0, 3).join(" · ")}
                    </span>
                  )}
                </span>
              </button>
            </li>
          ))}
        </ol>
      </aside>

      {expanded && (
        <FullList
          recommendations={recommendations}
          nodeById={nodeById}
          onClose={() => setExpanded(false)}
          onSelect={(id) => {
            setExpanded(false);
            onSelect(id);
          }}
        />
      )}
    </>
  );
}

function FullList({
  recommendations,
  nodeById,
  onClose,
  onSelect,
}: Omit<Props, "selectedId"> & { onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="rise pointer-events-auto absolute inset-0 z-40 overflow-y-auto bg-void/80 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="mx-auto my-10 max-w-3xl rounded-2xl border border-white/10 bg-panel/95 p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="font-display text-xl font-semibold text-leader">
            Recommendations · ranked
          </h2>
          <button
            onClick={onClose}
            aria-label="Close list"
            className="rounded-md px-2 text-dim transition hover:text-leader"
          >
            ✕
          </button>
        </div>
        <ol className="mt-5 space-y-3">
          {recommendations.map((r, i) => (
            <li key={r.id}>
              <button
                onClick={() => onSelect(r.id)}
                className="flex w-full gap-4 rounded-xl p-2 text-left transition hover:bg-white/5"
              >
                <span className="w-6 flex-none pt-1 text-right font-mono text-sm text-dim">
                  {i + 1}
                </span>
                {poster(nodeById.get(r.id)) ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={poster(nodeById.get(r.id)) as string}
                    alt=""
                    width={46}
                    height={69}
                    loading="lazy"
                    className="h-[4.6rem] w-[3.1rem] flex-none rounded object-cover ring-1 ring-white/10"
                  />
                ) : (
                  <div className="h-[4.6rem] w-[3.1rem] flex-none rounded bg-white/5" />
                )}
                <div className="min-w-0 flex-1">
                  <p className="font-display text-leader">
                    {r.title}{" "}
                    {r.year && <span className="font-mono text-xs text-dim">{r.year}</span>}{" "}
                    <span className="font-mono text-xs text-beam">{r.score.toFixed(2)}</span>
                  </p>
                  {r.shared_traits.length > 0 && (
                    <p className="mt-0.5 text-sm text-dim">{r.shared_traits.join(" · ")}</p>
                  )}
                  {r.because.length > 0 && (
                    <p className="mt-1 font-mono text-xs text-dim/80">
                      because you rated {r.because.map((b) => b.title).join(", ")}
                    </p>
                  )}
                </div>
              </button>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
