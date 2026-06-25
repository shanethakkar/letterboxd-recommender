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

## 2026-06-25 — TMDB id requires a per-film Letterboxd fetch
**Decision:** Resolve `slug→tmdb_id` via letterboxdpy `Movie(slug).tmdb_id` (one request per
film), cached permanently in Redis (`lb:slug2tmdb:{slug}`), with bounded-concurrency (4 workers)
+ jitter. Resolve only films with taste signal (rated/liked) + watchlist; skip unrated-watched.
**Why:** Contrary to SPEC §4.1's implication, letterboxdpy's bulk `get_films()` does NOT include
TMDB ids — only the per-film page does. The guardrail (id off the film page, no fuzzy matching)
still holds; this is purely a cost/latency reality. Permanent caching makes re-scrapes ~free.
**Affects:** SPEC §4.1 (scraper), `backend/scraper.py`. SPEC text left as-is (intent unchanged);
this note records the implementation reality.

## 2026-06-25 — Feature & scoring design (Phase 1)
**Decision:** Features = DictVectorizer multi-hot (genre/director/cast/keyword/decade/lang/runtime)
→ TF-IDF down-weighting → per-trait-type weights → L2 norm, fit on combined watched+candidates.
Score = cosine(taste) + small popularity prior + TMDB rec-graph provenance count; MMR for diversity;
"why" = nearest rated neighbours. Sparse profiles (<8 rated) shift weight to popularity/graph.
**Why:** Faithful to SPEC §4.3–4.4 using battle-tested scikit-learn; validated as coherent +
explainable against a real profile (@sthakkar).
**Affects:** `backend/features.py`, `backend/recommender.py`, `backend/tmdb.py`.

## 2026-06-25 — Local fakeredis does not persist across runs
**Decision:** Accept that the local `slug→tmdb_id` cache is in-process only (fakeredis) and is
re-built each run; rely on real Redis (prod, or a local Redis later) for cross-run persistence.
**Why:** No Redis service on this machine (Phase 0 decision). Acceptable for Phase 1 validation
(~85s re-scrape); revisit if local iteration speed becomes painful.
**Affects:** `backend/cache.py` behaviour locally; no contract change.
