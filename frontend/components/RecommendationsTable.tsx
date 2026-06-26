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

export default function RecommendationsTable({
  payload,
  onExplore,
  canExplore = true,
}: {
  payload: GraphPayload;
  onExplore: () => void;
  canExplore?: boolean;
}) {
  const [sort, setSort] = useState<SortKey>("match");
  const [genre, setGenre] = useState<string>("");

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
    <main className="atmosphere min-h-screen">
      <div className="mx-auto max-w-3xl px-5 pb-24 pt-8">
        {/* Header */}
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <Link href="/" className="font-mono text-xs text-dim transition hover:text-leader">
              ← home
            </Link>
            <h1 className="mt-2 font-display text-3xl font-semibold text-leader">
              Recommendations
            </h1>
            <p className="mt-1 font-mono text-xs text-dim">
              for @{payload.username} · {payload.stats.rated} rated · avg{" "}
              {payload.stats.avg_rating.toFixed(2)}
            </p>
          </div>
          {canExplore && (
            <button
              onClick={onExplore}
              className="rounded-full border border-beam/30 bg-beam/10 px-4 py-2 font-display text-sm text-beam transition hover:bg-beam/20"
            >
              ✦ Explore the constellation
            </button>
          )}
        </div>

        {/* Controls */}
        <div className="mt-6 flex flex-wrap items-center gap-2 border-y border-white/10 py-3">
          <span className="font-mono text-[11px] uppercase tracking-widest text-dim">sort</span>
          <Select label="Sort by" value={sort} onChange={(v) => setSort(v as SortKey)}>
            {SORTS.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </Select>
          <span className="ml-2 font-mono text-[11px] uppercase tracking-widest text-dim">
            genre
          </span>
          <Select label="Filter by genre" value={genre} onChange={setGenre}>
            <option value="">all</option>
            {genres.map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
          </Select>
          <span className="ml-auto font-mono text-[11px] text-dim">{recs.length} films</span>
        </div>

        {/* Cards */}
        <ol className="mt-4 space-y-3">
          {recs.map((r, i) => (
            <RecCard key={r.id} rec={r} rank={i + 1} />
          ))}
        </ol>
      </div>
    </main>
  );
}

function RecCard({ rec, rank }: { rec: Recommendation; rank: number }) {
  return (
    <li className="rise flex gap-4 rounded-xl border border-white/10 bg-panel/50 p-3 transition hover:border-white/20">
      {rec.poster_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={rec.poster_url}
          alt=""
          width={92}
          height={138}
          loading="lazy"
          className="h-[8.2rem] w-[5.5rem] flex-none rounded-md object-cover ring-1 ring-white/10"
        />
      ) : (
        <div className="h-[8.2rem] w-[5.5rem] flex-none rounded-md bg-white/5" />
      )}

      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-xs text-dim">{rank}</span>
          <h2 className="min-w-0 truncate font-display text-lg font-semibold text-leader">
            {rec.title}
          </h2>
          {rec.year && <span className="flex-none font-mono text-xs text-dim">{rec.year}</span>}
          <span className="ml-auto flex-none rounded-full bg-beam/15 px-2 py-0.5 font-mono text-xs text-beam">
            {rec.score.toFixed(2)} match
          </span>
        </div>

        <p className="mt-1 truncate font-mono text-xs text-dim">
          {[rec.director, rec.runtime ? `${rec.runtime}m` : null].filter(Boolean).join(" · ")}
        </p>

        {/* Review badges */}
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {rec.imdb_rating != null && <Badge label="IMDb" value={rec.imdb_rating.toFixed(1)} />}
          {rec.metascore != null && <Badge label="Meta" value={String(rec.metascore)} />}
          {rec.rotten_tomatoes != null && (
            <Badge label="RT" value={`${rec.rotten_tomatoes}%`} />
          )}
          {rec.genres.slice(0, 3).map((g) => (
            <span key={g} className="rounded-full border border-white/10 px-2 py-0.5 font-mono text-[10px] text-dim">
              {g}
            </span>
          ))}
        </div>

        {/* The "why" — our differentiator */}
        {rec.because.length > 0 && (
          <p className="mt-2.5 text-sm leading-snug">
            <span className="font-mono text-[10px] uppercase tracking-widest text-beam/80">
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
    <span className="rounded border border-white/10 px-1.5 py-0.5 font-mono text-[10px] text-dim">
      {label} <span className="text-leader">{value}</span>
    </span>
  );
}

function Select({
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
      className="cursor-pointer rounded-full border border-white/10 bg-panel px-3 py-1 font-mono text-xs text-leader outline-none transition hover:border-beam/40 [&>option]:bg-panel"
    >
      {children}
    </select>
  );
}
