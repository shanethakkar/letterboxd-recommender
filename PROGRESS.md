# Progress

_Last updated: 2026-06-25 · Current phase: 1 complete — next is Phase 2 (projection + payload)_

## Phase 0 — Backend skeleton
- [x] Project scaffolding: `.gitignore`, `.env` (+ `.env.example`), `CLAUDE.md`, `PROGRESS.md`, `DECISIONS.md`
  - Finding: machine has no system Python/Docker/Redis/WSL; `uv` is installed and manages
    cpython-3.12. Toolchain = uv + project `.venv` (matches user's other repos). See DECISIONS.
- [x] `.venv` created (uv, Python 3.12) + backend deps installed
- [x] FastAPI app boots; `GET /health` returns redis status
  - Finding: Redis wired via in-process `fakeredis` for local dev (REDIS_URL blank);
    same `redis.asyncio` interface, so prod is a URL swap only.
- [x] TMDB client written; payload parsing unit-tested (no network, httpx MockTransport)
  - Finding: Letterboxd→TMDB mapping uses the TMDB id directly; `append_to_response=
    credits,keywords,recommendations,similar` hydrates a film in one call.
- [x] **TMDB validated end-to-end on 2 real films** (key pasted into `.env`)
  - Evidence: `GET /api/films/27205` → Inception (2010), dir. Christopher Nolan, genres
    [Action, Science Fiction, Adventure], poster_url, 20 recs + 20 similar.
    `GET /api/films/49047` → Gravity (2013), dir. Alfonso Cuarón. `/health` → redis ok,
    tmdb_key_present true. ruff clean (check+format); pytest 4 passed.
  - Finding: SPEC §5's example id `tmdb:49047` was labelled "Prisoners" but actually resolves
    to Gravity — the spec's example ids are illustrative only; real mapping is by id and correct.
- Next: Phase 0 complete. Start Phase 1 (recommender, no UI) in a new session.

## Phase 0 retro (what I learned)
- This machine has no system Python/Redis/Docker/WSL; the working toolchain is `uv` (manages
  cpython-3.12) + project `.venv`, and Python tooling must run via the PowerShell tool (Git Bash
  can't see uv). Recorded in CLAUDE.md + DECISIONS.md.
- Minor: `starlette.testclient` emits a deprecation warning about httpx; harmless for now.

## Phase 1 — Recommender (no UI) — COMPLETE
- [x] Scraper (`scraper.py`) — letterboxdpy wrapped for async; rated/liked/watchlist;
      permanent Redis `slug→tmdb_id` cache; private/not-found/empty mapped to domain errors.
  - Finding: letterboxdpy bulk list omits TMDB ids → per-film `Movie(slug).tmdb_id` fetch
    (one Letterboxd request/film). See DECISIONS (2026-06-25, per-film tmdb id).
- [x] Features (`features.py`) — DictVectorizer multi-hot + TF-IDF down-weighting + per-type
      weights + L2 norm, fit on combined watched+candidates.
- [x] tmdb.py extended — `get_movies` batch, `discover_backfill`, `build_candidate_pool`
      (provenance counts = rec-graph signal); `Film` gained popularity + rating/liked fields.
- [x] Recommender (`recommender.py`) — taste vector (rating-weighted, below-mean pulls
      negative, liked bump), cosine + popularity prior + graph signal, MMR diversity,
      "why" neighbours + shared_traits, sparse-profile fallback.
- [x] Tests — 18 pass (Phase 0 + features/recommender/scraper), deterministic, no network.
      ruff check + format clean.
- [x] **Validated against my own profile (@sthakkar) — recs gut-checked: PASS**
  - Evidence: 364 films / 217 rated (avg 3.86). Top-20 recs are coherent crime/thriller/neo-noir
    (The Getaway, Carlito's Way, 25th Hour, Cop Land, Talented Mr. Ripley…) with honest
    "because you rated GoodFellas/The Departed/Se7en…" traces, and MMR diversifies into the
    user's sci-fi (Contact, Metropolis), drama (Finding Forrester), and classic-mystery (Laura)
    sub-tastes. Pipeline timing: scrape ~85–110s (first run), enrich + candidates ~5–30s.
- Next: Phase 2 — UMAP projection, clusters, kNN edges, assemble the SPEC §5 graph payload.

## Phase 1 retro (what I learned)
- letterboxdpy's bulk film list has NO tmdb ids; per-film `Movie(slug)` fetch is the scrape
  bottleneck → permanent Redis cache + bounded concurrency (4 workers, jitter) handled it; the
  singleton curl_cffi session was fine at concurrency 4 in practice.
- **fakeredis is per-process**, so the slug→tmdb cache does NOT persist across local runs
  (re-scrape each run ~85s). Real Redis in prod/local would make re-runs instant. Minor; noted.
- TF-IDF + per-type weighting produced sensible, explainable similarities on the first try;
  MMR materially improved diversity (without it the top-20 was nearly all mob films).
- Cosine scores sit in a modest absolute range (~0.23–0.35) — fine for ranking; may rescale for
  display in the UI later.

## Phase 2 — Projection + payload
- [ ] UMAP coords, clusters, edges; full graph payload serialized + eyeballed

## Phase 3 — Static constellation
- [ ] Next.js + deck.gl renders the settled map (posters, edges, hover, panel, filters)

## Phase 4 — SSE + pipeline intro
- [ ] Job endpoint + SSE; four-act animation; crystallization tween

## Phase 5 — Polish + deploy
- [ ] Mobile tuning, reduced-motion, error states, share links; deploy

## Open loops / blockers
- TMDB live validation blocked on `TMDB_API_KEY` being pasted into `.env` (intentional — secret).
