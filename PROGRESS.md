# Progress

_Last updated: 2026-06-25 · Current phase: 0 — Backend skeleton_

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

## Phase 1 — Recommender (no UI)
- [ ] Scraper -> features -> taste vector -> scored recs
- [ ] Validated against my own profile (recs gut-checked)

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
