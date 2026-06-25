# Constellation — Project Guide for Claude Code

A deployed site that maps a Letterboxd user's taste and recommends films, rendered
as an explainable WebGL constellation. Plan of record: **SPEC.md** (read the relevant
phase before working; do NOT inline the whole spec into context).

## Golden workflow rules
- Read `SPEC.md` (the relevant phase) and `PROGRESS.md` at the start of any task.
- Use **Plan Mode** for every phase and any multi-file change. Do not edit files or run
  commands while planning. Implement only after the plan is approved.
- Build strictly in phase order (Phase 0 → 5). One phase per session; do not jump ahead.
- **Update `PROGRESS.md` after every meaningful step**: check off the task, note what was
  done, any findings, and the next action. PROGRESS.md must always reflect reality.
- **If execution diverges from the approved plan or from SPEC.md, STOP and re-enter Plan
  Mode.** Do not silently improvise a different approach.
- When a decision changes the design: (1) update `SPEC.md` so it reflects the new intent,
  and (2) append an entry to `DECISIONS.md` (what changed, why, date). Never let SPEC.md
  go stale.
- Verify with evidence: show the test output, the command run and its result, or a
  screenshot. Do not assert success without proof.
- End each phase with a short retro ("what did I learn?") and route it: durable project
  rules here in CLAUDE.md, area conventions to `.claude/rules/`, design changes to
  DECISIONS.md.
- Commit per logical change with a descriptive message. Never commit secrets.

## Stack
- Backend: Python 3.12, FastAPI, httpx (async), scikit-learn, numpy, umap-learn, redis.
- Frontend: TypeScript, Next.js (React), deck.gl (PixiJS only if needed).
- Hosting: backend on Render/Railway/Fly (NOT serverless); frontend on Vercel.

## Environment (this machine — Windows 11)
- **No system Python / Docker / Redis / WSL.** Python comes from **`uv`** (already installed,
  on the PowerShell PATH), which manages cpython-3.12. Match the existing per-project `.venv`
  convention used in the user's other repos.
- The **Bash tool's Git Bash does NOT see `uv`/Python** — run Python tooling via the
  **PowerShell tool** (or activate `.venv\Scripts\Activate.ps1`).
- **Redis locally = in-process `fakeredis`** (no service to run). Set `REDIS_URL` to a real
  Redis only for production. See DECISIONS.md.

## Commands (PowerShell)
- Create venv:        `uv venv --python 3.12`
- Install backend:    `uv pip install -r backend/requirements.txt`
- Run backend:        `uv run uvicorn backend.app:app --reload`
- Backend tests:      `uv run pytest -q`
- Lint/format:        `uv run ruff check . ; uv run ruff format .`
- Frontend dev:       `cd frontend ; npm run dev`            (later phases)
- Frontend checks:    `npm run typecheck ; npm run lint`     (later phases)

## Code conventions
- Python: full type hints; Pydantic models for all API payloads; async I/O for scrape +
  TMDB; ruff + ruff format; no bare excepts; secrets via `.env` (provide `.env.example`).
- TypeScript: `strict` mode, no `any`; functional components + hooks; the graph payload
  type mirrors SPEC §5 exactly.
- Secrets (TMDB key, etc.) NEVER in code, commits, or logs. `.env` only.

## Architecture guardrails (do not violate without a DECISIONS.md entry)
- Backend is NOT serverless — scrape jobs are long-running.
- UMAP projection runs **server-side only** — never run UMAP/t-SNE in the browser; ship
  precomputed coordinates and animate the interpolation.
- Map Letterboxd → TMDB via the TMDB id on the Letterboxd film page. No fuzzy title matching.
- The graph payload (SPEC §5) is the contract between backend and frontend. Do not change
  its shape without updating SPEC.md and DECISIONS.md.
- Phase 1 (recommender correctness) must be validated against a real profile BEFORE any UI work.
- Cache aggressively in Redis and rate-limit politely; minimize hits to Letterboxd.

## Installed skills (use where relevant)
- `emil-design-eng` — UI polish & animation decisions. Use in **Phase 3–4** for the
  constellation feel and the crystallization tween.
- `fixing-motion-performance` — animation perf audit. Use in **Phase 3–4** (thousands of
  poster sprites; SPEC §8 flags crystallization jank).
- `web-design-guidelines` — UI/accessibility/UX audit. Use in **Phase 5** polish.
- (All three are frontend-only — not used during backend phases.)

## Where things live
- `backend/` — scraper, tmdb, features, recommender, projection, cache, app (FastAPI).
- `frontend/` — Next.js app; `/u/[username]` route; deck.gl render layers (later phases).
- `SPEC.md` (what) · `PROGRESS.md` (where) · `DECISIONS.md` (why) · this file (how).
