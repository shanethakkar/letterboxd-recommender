"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

export default function Landing() {
  const router = useRouter();
  const [username, setUsername] = useState("");

  function go(e: React.FormEvent) {
    e.preventDefault();
    const u = username.trim().replace(/^@/, "");
    if (u) router.push(`/u/${encodeURIComponent(u)}`);
  }

  return (
    <main className="atmosphere relative flex min-h-screen flex-col items-center justify-center overflow-hidden px-6">
      <Starfield />

      <div className="relative z-10 w-full max-w-xl text-center">
        <p className="rise font-mono text-[11px] uppercase tracking-[0.35em] text-dim">
          Letterboxd · taste cartography
        </p>

        <h1
          className="rise mt-6 font-display text-6xl font-semibold tracking-tight text-leader sm:text-7xl"
          style={{ animationDelay: "60ms" }}
        >
          Constellation
        </h1>

        <p
          className="rise mx-auto mt-5 max-w-md text-balance text-base leading-relaxed text-dim"
          style={{ animationDelay: "120ms" }}
        >
          Enter a public Letterboxd username and watch your ratings crystallise into a
          navigable map of taste — every recommendation wired to the films that earned it.
        </p>

        <form
          onSubmit={go}
          className="rise mx-auto mt-10 flex max-w-md items-center gap-2"
          style={{ animationDelay: "180ms" }}
        >
          <div className="flex flex-1 items-center rounded-full border border-white/10 bg-panel/70 pl-5 pr-2 backdrop-blur transition focus-within:border-beam/50">
            <span className="font-mono text-dim">@</span>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="username…"
              name="username"
              autoComplete="off"
              autoFocus
              spellCheck={false}
              autoCapitalize="none"
              className="w-full bg-transparent px-2 py-3 font-mono text-leader placeholder:text-dim/60 focus:outline-none"
              aria-label="Letterboxd username"
            />
            <button
              type="submit"
              disabled={!username.trim()}
              className="rounded-full bg-leader px-5 py-2 font-display text-sm font-medium text-void transition hover:bg-beam disabled:cursor-not-allowed disabled:opacity-30"
            >
              Map it
            </button>
          </div>
        </form>

        <p
          className="rise mt-6 font-mono text-xs text-dim/70"
          style={{ animationDelay: "240ms" }}
        >
          try{" "}
          {["sthakkar", "nmcassa"].map((u, i) => (
            <span key={u}>
              {i > 0 && <span className="text-dim/40"> · </span>}
              <Link
                href={`/u/${u}`}
                className="text-dim underline-offset-4 transition hover:text-beam hover:underline"
              >
                {u}
              </Link>
            </span>
          ))}
        </p>
      </div>
    </main>
  );
}

/** A quiet scatter of stars — a hint of the constellation to come. */
function Starfield() {
  const stars = Array.from({ length: 60 }, (_, i) => {
    const r = ((i * 9301 + 49297) % 233280) / 233280;
    const r2 = ((i * 49297) % 233280) / 233280;
    return {
      left: `${(r * 100).toFixed(2)}%`,
      top: `${(r2 * 100).toFixed(2)}%`,
      size: r > 0.92 ? 2 : 1,
      opacity: 0.1 + r2 * 0.5,
    };
  });
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0">
      {stars.map((s, i) => (
        <span
          key={i}
          className="absolute rounded-full bg-leader"
          style={{ left: s.left, top: s.top, width: s.size, height: s.size, opacity: s.opacity }}
        />
      ))}
    </div>
  );
}
