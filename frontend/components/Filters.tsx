"use client";

import type { Cluster } from "@/lib/types";

export interface FilterState {
  showWatched: boolean;
  showRecommended: boolean;
  cluster: number | null;
  genre: string | null;
}

interface Props {
  clusters: Cluster[];
  genres: string[];
  state: FilterState;
  setState: (s: FilterState) => void;
}

export default function Filters({ clusters, genres, state, setState }: Props) {
  const update = (patch: Partial<FilterState>) => setState({ ...state, ...patch });
  const dirty =
    !state.showWatched ||
    !state.showRecommended ||
    state.cluster !== null ||
    state.genre !== null;

  return (
    <div className="pointer-events-auto absolute left-1/2 top-4 z-20 flex -translate-x-1/2 items-center gap-2 rounded-full border border-white/10 bg-panel/70 px-2 py-1.5 backdrop-blur">
      <Chip active={state.showWatched} onClick={() => update({ showWatched: !state.showWatched })}>
        watched
      </Chip>
      <Chip
        active={state.showRecommended}
        onClick={() => update({ showRecommended: !state.showRecommended })}
      >
        recs
      </Chip>

      <span className="mx-0.5 h-4 w-px bg-white/10" />

      <Select
        label="Filter by cluster"
        value={state.cluster === null ? "" : String(state.cluster)}
        onChange={(v) => update({ cluster: v === "" ? null : Number(v) })}
      >
        <option value="">all clusters</option>
        {clusters.map((c) => (
          <option key={c.id} value={c.id}>
            {c.label ?? `cluster ${c.id}`}
          </option>
        ))}
      </Select>

      <Select
        label="Filter by genre"
        value={state.genre ?? ""}
        onChange={(v) => update({ genre: v === "" ? null : v })}
      >
        <option value="">all genres</option>
        {genres.map((g) => (
          <option key={g} value={g}>
            {g}
          </option>
        ))}
      </Select>

      {dirty && (
        <button
          onClick={() =>
            setState({ showWatched: true, showRecommended: true, cluster: null, genre: null })
          }
          className="rounded-full px-2 font-mono text-[11px] text-dim transition hover:text-beam"
          aria-label="Clear filters"
        >
          clear
        </button>
      )}
    </div>
  );
}

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-full px-3 py-1 font-mono text-[11px] transition ${
        active ? "bg-leader text-void" : "text-dim hover:text-leader"
      }`}
    >
      {children}
    </button>
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
      className="cursor-pointer rounded-full bg-panel px-2 py-1 font-mono text-[11px] text-dim outline-none transition hover:text-leader [&>option]:bg-panel [&>option]:text-leader"
    >
      {children}
    </select>
  );
}
