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

## End-of-phase checklist — Definition of Done (do NOT skip; runs every phase)
Before declaring any phase complete, ALL of these must be done — treat it as a hard gate:
1. **PROGRESS.md updated** — check off the phase's tasks, record findings + the next concrete
   action, and bump the `_Last updated_` line. PROGRESS.md must reflect reality at all times.
2. **DECISIONS.md updated** *(if anything diverged from SPEC)* — append a dated entry (what
   changed, why, what it affects). If the design *intent* changed, also edit **SPEC.md** so it
   never goes stale. If nothing diverged, state that explicitly in the phase notes.
3. **Verified with evidence** — tests/commands/output or a screenshot pasted, not just asserted.
4. **Phase retro** captured in PROGRESS.md ("what did I learn?").
5. **Commit + push** — commit the phase with a descriptive message, then `git push` to `origin`
   (see Git below). Never commit `.env` or any secret.

Mid-phase, also update PROGRESS.md / append DECISIONS.md the moment something meaningful changes —
don't batch it all to the end, and never let a design change land without a DECISIONS.md entry.

## Git
- Remote `origin` is the GitHub repo; pushes use Git Credential Manager (already configured).
- **Commit at the end of every phase and push to `origin`.** Smaller logical commits within a
  phase are encouraged. End commit messages with the Co-Authored-By trailer.
- `.env`, `uv.lock`, and `.venv/` are gitignored — verify `git status` shows no secrets before committing.

## Stack
- Backend: Python 3.12, FastAPI, httpx (async), scikit-learn, numpy, umap-learn, redis.
- Frontend: TypeScript, Next.js (React), deck.gl (PixiJS only if needed).
- Hosting: backend on Render/Railway/Fly (NOT serverless); frontend on Vercel.

## Environment (this machine — Windows 11)
- **No system Python / Docker / Redis / WSL.** Python comes from **`uv`** (already installed,
  on the PowerShell PATH), which manages cpython-3.12. Match the existing per-project `.venv`
  convention used in the user's other repos.
- The **Bash tool's Git Bash does NOT see `uv`/Python** — run Python tooling via the
  **PowerShell tool**. **`node`/`npm`/`npx` ARE on Git Bash** — run frontend tooling via the Bash tool.
- **Redis locally = in-process `fakeredis`** (no service to run). Set `REDIS_URL` to a real
  Redis only for production. See DECISIONS.md.

## Commands
Backend (PowerShell — `uv`):
- Create venv:        `uv venv --python 3.12`
- Install backend:    `uv pip install -r backend/requirements.txt`
- Run backend:        `uv run python -m uvicorn backend.app:app --app-dir . --port 8000`
  (plain `uv run uvicorn …` fails — the project root isn't on `sys.path`; use `python -m` + `--app-dir`)
- Backend tests:      `uv run pytest -q`
- Lint/format:        `uv run ruff check . ; uv run ruff format .`

Frontend (Bash — `npm`; Next.js 16 + deck.gl, lives in `frontend/`):
- Dev:       `cd frontend && npm run dev`           (http://localhost:3000)
- Typecheck: `cd frontend && npx tsc --noEmit`      (no `typecheck` script in Next 16)
- Lint:      `cd frontend && npm run lint`
- Build:     `cd frontend && npm run build`
- API base via `NEXT_PUBLIC_API_BASE` (defaults to `http://localhost:8000`).
- ⚠️ `frontend/AGENTS.md` warns this is **Next.js 16** (breaking changes) — read
  `frontend/node_modules/next/dist/docs/` before writing Next code.

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
