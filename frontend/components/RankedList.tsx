"use client";

import Link from "next/link";

import type { GraphPayload } from "@/lib/types";

/** Graceful degradation (SPEC §6.5): when WebGL is unavailable, the map can't render,
 * so fall back to a plain ranked list of recommendations. */
export default function RankedList({ payload }: { payload: GraphPayload }) {
  return (
    <main className="atmosphere min-h-screen px-6 py-10">
      <div className="mx-auto max-w-2xl">
        <Link href="/" className="font-mono text-xs text-dim hover:text-leader">
          ← home
        </Link>
        <h1 className="mt-4 font-display text-3xl font-semibold text-leader">
          @{payload.username}
        </h1>
        <p className="mt-1 font-mono text-xs text-dim">
          {payload.stats.rated} rated · avg {payload.stats.avg_rating.toFixed(2)} · WebGL
          unavailable — showing the ranked list
        </p>

        <ol className="mt-8 space-y-5">
          {payload.recommendations.map((r, i) => (
            <li key={r.id} className="flex gap-4">
              <span className="w-6 flex-none pt-0.5 text-right font-mono text-sm text-dim">
                {i + 1}
              </span>
              <div className="min-w-0">
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
            </li>
          ))}
        </ol>
      </div>
    </main>
  );
}
