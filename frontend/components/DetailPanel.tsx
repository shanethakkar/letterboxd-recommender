"use client";

import type { GraphNode, Recommendation } from "@/lib/types";

interface Props {
  node: GraphNode;
  recommendation: Recommendation | null;
  onClose: () => void;
  onSelectSeed: (id: string) => void;
}

function tmdbId(id: string): string {
  return id.replace(/^tmdb:/, "");
}

export default function DetailPanel({ node, recommendation, onClose, onSelectSeed }: Props) {
  const isRec = node.type === "recommended";
  return (
    <aside className="rise pointer-events-auto absolute right-4 top-4 z-20 flex max-h-[calc(100vh-2rem)] w-[20rem] flex-col overflow-hidden rounded-xl border border-white/10 bg-panel/85 backdrop-blur-md">
      <div className="flex items-start gap-3 p-4">
        {node.poster_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={node.poster_url}
            alt=""
            width={75}
            height={112}
            loading="lazy"
            className="h-28 w-[4.7rem] flex-none rounded-md object-cover ring-1 ring-white/10"
          />
        ) : (
          <div className="h-28 w-[4.7rem] flex-none rounded-md bg-white/5" />
        )}
        <div className="min-w-0 flex-1">
          <span
            className={`font-mono text-[10px] uppercase tracking-widest ${
              isRec ? "text-beam" : "text-dim"
            }`}
          >
            {isRec ? "recommended" : "watched"}
          </span>
          <h2 className="mt-1 font-display text-lg font-semibold leading-tight text-leader">
            {node.title}
          </h2>
          <p className="mt-0.5 font-mono text-xs text-dim">
            {node.year ?? "—"}
            {node.director ? ` · ${node.director}` : ""}
          </p>
          <p className="mt-2 font-mono text-sm">
            {isRec ? (
              <span className="text-beam">match {(node.score ?? 0).toFixed(2)}</span>
            ) : (
              <span className="text-leader">
                {"★".repeat(Math.round(node.rating ?? 0))}
                <span className="text-dim/50">
                  {"★".repeat(5 - Math.round(node.rating ?? 0))}
                </span>{" "}
                <span className="text-dim">{(node.rating ?? 0).toFixed(1)}</span>
              </span>
            )}
          </p>
        </div>
        <button
          onClick={onClose}
          aria-label="Close"
          className="flex-none rounded-md px-1.5 text-dim transition hover:text-leader"
        >
          ✕
        </button>
      </div>

      <div className="overflow-y-auto px-4 pb-4">
        {node.genres.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {node.genres.map((g) => (
              <span
                key={g}
                className="rounded-full border border-white/10 px-2 py-0.5 font-mono text-[10px] text-dim"
              >
                {g}
              </span>
            ))}
          </div>
        )}

        {isRec && recommendation && (
          <div className="mt-4">
            {recommendation.shared_traits.length > 0 && (
              <p className="text-sm text-dim">
                {recommendation.shared_traits.join(" · ")}
              </p>
            )}
            <p className="mt-3 font-mono text-[10px] uppercase tracking-widest text-dim">
              because you rated
            </p>
            <ul className="mt-1.5 space-y-1">
              {recommendation.because.map((b) => (
                <li key={b.id}>
                  <button
                    onClick={() => onSelectSeed(b.id)}
                    className="group flex w-full items-baseline justify-between gap-2 rounded-md px-1 py-0.5 text-left transition hover:bg-white/5"
                  >
                    <span className="truncate text-sm text-leader group-hover:text-beam">
                      {b.title}
                    </span>
                    <span className="flex-none font-mono text-xs text-dim">
                      {b.contribution.toFixed(2)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        <a
          href={`https://www.themoviedb.org/movie/${tmdbId(node.id)}`}
          target="_blank"
          rel="noreferrer"
          className="mt-4 inline-block font-mono text-xs text-dim underline-offset-4 transition hover:text-beam hover:underline"
        >
          view on TMDB ↗
        </a>
      </div>
    </aside>
  );
}
