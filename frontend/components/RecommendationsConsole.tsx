"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import type { GraphPayload, Recommendation } from "@/lib/types";

type SortKey = "match" | "imdb" | "metascore" | "year" | "title";

const SORTS: { key: SortKey; label: string }[] = [
  { key: "match", label: "best match" },
  { key: "imdb", label: "IMDb rating" },
  { key: "metascore", label: "Metacritic" },
  { key: "year", label: "newest" },
  { key: "title", label: "A–Z" },
];

function sortRecs(recs: Recommendation[], key: SortKey): Recommendation[] {
  const lo = -Infinity;
  const by: Record<SortKey, (r: Recommendation) => number | string> = {
    match: (r) => -r.score,
    imdb: (r) => -(r.imdb_rating ?? lo),
    metascore: (r) => -(r.metascore ?? lo),
    year: (r) => -(r.year ?? lo),
    title: (r) => r.title.toLowerCase(),
  };
  return [...recs].sort((a, b) => {
    const va = by[key](a);
    const vb = by[key](b);
    return va < vb ? -1 : va > vb ? 1 : 0;
  });
}

export default function RecommendationsConsole({
  payload,
  onExplore,
  canExplore = true,
}: {
  payload: GraphPayload;
  onExplore: () => void;
  canExplore?: boolean;
}) {
  const [sort, setSort] = useState<SortKey>("match");
  const [genre, setGenre] = useState("");

  const genres = useMemo(
    () => Array.from(new Set(payload.recommendations.flatMap((r) => r.genres))).sort(),
    [payload.recommendations],
  );

  const recs = useMemo(() => {
    const filtered = genre
      ? payload.recommendations.filter((r) => r.genres.includes(genre))
      : payload.recommendations;
    return sortRecs(filtered, sort);
  }, [payload.recommendations, genre, sort]);

  return (
    <div className="relative z-10 mx-auto max-w-2xl px-4 py-10 sm:py-16">
      <div className="rise glass overflow-hidden rounded-[1.75rem]">
        {/* header */}
        <header className="flex flex-wrap items-end justify-between gap-4 border-b border-white/10 px-6 pb-5 pt-6">
          <div>
            <Link
              href="/"
              className="font-mono text-[11px] uppercase tracking-[0.3em] text-dim transition hover:text-leader"
            >
              ← home
            </Link>
            <p className="mt-2 font-mono text-[11px] uppercase tracking-[0.3em] text-dim">
              @{payload.username} · {payload.stats.rated} rated · avg{" "}
              {payload.stats.avg_rating.toFixed(2)}
            </p>
            <h1 className="mt-1.5 font-display text-[2rem] font-semibold leading-none text-leader">
              Recommendations
            </h1>
          </div>
          {canExplore && (
            <button
              type="button"
              onClick={onExplore}
              className="rounded-full border border-beam/30 bg-beam/10 px-4 py-2 font-display text-sm text-beam shadow-[inset_0_1px_0_rgba(255,255,255,0.12)] transition duration-150 ease-out hover:bg-beam/20 active:scale-[0.97]"
            >
              ✦ Explore the constellation
            </button>
          )}
        </header>

        {/* controls */}
        <div className="flex flex-wrap items-center gap-2 border-b border-white/10 px-6 py-3">
          <span className="font-mono text-[10px] uppercase tracking-[0.25em] text-dim">sort</span>
          <GlassSelect label="Sort by" value={sort} onChange={(v) => setSort(v as SortKey)}>
            {SORTS.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </GlassSelect>
          <span className="ml-2 font-mono text-[10px] uppercase tracking-[0.25em] text-dim">genre</span>
          <GlassSelect label="Filter by genre" value={genre} onChange={setGenre}>
            <option value="">all</option>
            {genres.map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
          </GlassSelect>
          <span className="ml-auto font-mono text-[10px] text-dim">{recs.length} films</span>
        </div>

        {/* cards */}
        <ol className="space-y-3 p-4 sm:p-5">
          {recs.map((r, i) => (
            <Card key={r.id} rec={r} rank={i + 1} index={i} />
          ))}
        </ol>
      </div>
    </div>
  );
}

function Card({ rec, rank, index }: { rec: Recommendation; rank: number; index: number }) {
  return (
    <li
      className="rise glass-card flex gap-4 rounded-2xl p-3"
      style={{ animationDelay: `${0.05 + index * 0.04}s` }}
    >
      {rec.poster_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={rec.poster_url}
          alt=""
          width={92}
          height={138}
          loading="lazy"
          className="h-[8.4rem] w-[5.6rem] flex-none rounded-lg object-cover shadow-lg ring-1 ring-white/15"
        />
      ) : (
        <div className="h-[8.4rem] w-[5.6rem] flex-none rounded-lg bg-white/5 ring-1 ring-white/10" />
      )}

      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-xs text-dim">{rank}</span>
          <h2 className="min-w-0 truncate font-display text-lg font-semibold text-leader">
            {rec.title}
          </h2>
          {rec.year && <span className="flex-none font-mono text-xs text-dim">{rec.year}</span>}
          <span className="ml-auto flex-none rounded-full bg-beam/15 px-2 py-0.5 font-mono text-xs text-beam ring-1 ring-beam/20">
            {rec.score.toFixed(2)} match
          </span>
        </div>

        <p className="mt-1 truncate font-mono text-xs text-dim">
          {[rec.director, rec.runtime ? `${rec.runtime}m` : null].filter(Boolean).join(" · ")}
        </p>

        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {rec.imdb_rating != null && <Badge label="IMDb" value={rec.imdb_rating.toFixed(1)} />}
          {rec.metascore != null && <Badge label="Meta" value={String(rec.metascore)} />}
          {rec.rotten_tomatoes != null && <Badge label="RT" value={`${rec.rotten_tomatoes}%`} />}
          {rec.genres.slice(0, 3).map((g) => (
            <span
              key={g}
              className="rounded-full border border-white/10 px-2 py-0.5 font-mono text-[10px] text-dim"
            >
              {g}
            </span>
          ))}
        </div>

        {/* the "why" — our differentiator */}
        {rec.because.length > 0 && (
          <p className="mt-2.5 text-sm leading-snug">
            <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-beam/80">
              because you rated{" "}
            </span>
            <span className="text-leader">{rec.because.map((b) => b.title).join(", ")}</span>
          </p>
        )}

        <div className="mt-2 flex gap-3 font-mono text-[11px] text-dim">
          <a
            href={`https://letterboxd.com/tmdb/${rec.tmdb_id}/`}
            target="_blank"
            rel="noreferrer"
            className="underline-offset-4 transition hover:text-beam hover:underline"
          >
            Letterboxd ↗
          </a>
          <a
            href={`https://www.themoviedb.org/movie/${rec.tmdb_id}`}
            target="_blank"
            rel="noreferrer"
            className="underline-offset-4 transition hover:text-beam hover:underline"
          >
            TMDB ↗
          </a>
        </div>
      </div>
    </li>
  );
}

function Badge({ label, value }: { label: string; value: string }) {
  return (
    <span className="rounded border border-white/10 bg-white/[0.03] px-1.5 py-0.5 font-mono text-[10px] text-dim">
      {label} <span className="text-leader">{value}</span>
    </span>
  );
}

function GlassSelect({
  label,
  value,
  onChange,
  children,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  children: React.ReactNode;
}) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="cursor-pointer rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 font-mono text-xs text-leader outline-none backdrop-blur transition hover:border-beam/40 focus-visible:ring-2 focus-visible:ring-beam/40 [&>option]:bg-panel"
    >
      {children}
    </select>
  );
}
