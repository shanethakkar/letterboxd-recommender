# Decision Log

## 2026-06-22 — Candidate pool source
**Decision:** Use TMDB recommendations + similar (top-rated seeds) + acclaimed backfill.
**Why:** No standing multi-user corpus, so a content-based hybrid avoids cold-start.
**Affects:** SPEC 4.2, 4.4.

## 2026-06-25 — Toolchain: uv + project .venv on Python 3.12
**Decision:** Manage the backend with `uv` (already installed) and a project-local `.venv`
pinned to Python 3.12. Keep `backend/requirements.txt` as the dependency manifest; install it
with `uv pip install -r backend/requirements.txt`.
**Why:** This machine has no system Python — only Anaconda (3.13) and `uv` (managing cpython-3.12).
The user's other repos already use uv-built `.venv`s on 3.12. Python 3.12 also has materially
better wheel support for the later ML stack (numba/umap-learn lag on 3.13). Keeping
`requirements.txt` preserves the command set documented in SPEC §10.1.
**Affects:** CLAUDE.md (Commands/Environment), SPEC §10.1 commands (now run via `uv`).

## 2026-06-25 — Local Redis via fakeredis
**Decision:** For local development, use in-process `fakeredis` when `REDIS_URL` is blank;
use a real Redis (`redis.asyncio.from_url`) when `REDIS_URL` is set. Production sets `REDIS_URL`.
**Why:** No Docker/WSL/Redis on this machine and no container infra. `fakeredis` exercises the
exact `redis.asyncio` client interface, so "Redis wired" is honest and the prod swap is a URL
change only — no separate code path for the cache logic.
**Affects:** SPEC §4.6 (cache), `backend/cache.py`, `.env`.

## 2026-06-25 — Run Python tooling via PowerShell, not the Bash tool
**Decision:** All Python/uv commands run through the PowerShell tool (or an activated venv).
**Why:** The Bash tool's Git Bash does not see `uv` or Python on this machine; PowerShell does.
**Affects:** CLAUDE.md (Environment/Commands); operational only, no design impact.
