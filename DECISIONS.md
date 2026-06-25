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

## 2026-06-25 — Recommender tuned toward mainstream + rating-aware "why"
**Decision:** Bias recommendations toward well-rated, popular, and more recent films, and draw
explanations only from highly-rated watched films. Concretely: (1) a TMDB **vote-count floor**
(default 500) drops obscure candidates pre-scoring; (2) the weak popularity prior is replaced by a
**composite mainstream prior** = Bayesian quality + log(vote_count) popularity + recency; (3) all
three score components (content / graph / prior) are **min-max normalized** so blend weights mean
what they say, with new mainstream-leaning defaults (0.55 / 0.15 / 0.45); (4) the "why" neighbours
are restricted to films rated ≥ the user's average (or liked). All knobs are per-request parameters.
**Why:** The first gut-check (@sthakkar) surfaced too many obscure/old films (Shattered '91, Bunny
Lake '65, Metropolis '27) — pure taste-matching + TF-IDF's bias toward rare traits + no quality/
recency signal + no vote floor. User asked to weight toward recognizable, recent, well-rated films,
and noted the "why" should cite films they rated highly. Re-run evidence: median TMDB votes rose to
~3,256 and mean year to 2004, with on-taste, recognizable titles (Trainspotting, Once Upon a Time in
America, Cape Fear, Blue Velvet, Inside Man, The Killer).
**Affects:** SPEC §4.4 (rewritten), `backend/recommender.py`, `backend/tmdb.py` (richer discover
backfill), `backend/validate_recommender.py` (mainstream-shift stats). Knobs are designed to back the
deferred per-user mood/genre/year filters (SPEC §6.4 / §9).

## 2026-06-25 — Add IMDb + Metacritic (OMDb) to the quality signal
**Decision:** Blend external review scores into the recommender's quality term. Capture each film's
`imdb_id` from TMDB (free), then a new `backend/omdb.py` enriches the **top ~120 contenders** with
IMDb + Metacritic + Rotten Tomatoes via the OMDb API, cached permanently in Redis (`omdb:{imdb_id}`).
The quality sub-score becomes the per-film mean of available 0–10 signals (TMDB Bayesian + IMDb +
Metascore/10). Orchestration is **two-pass**: pass-1 ranks candidates (MMR λ=1 ⇒ pure relevance) to
pick the shortlist, enrich it, then pass-2 re-ranks with review-aware quality.
**Why:** User: "more likely to enjoy a well-reviewed movie." TMDB's audience score alone is mushy and
not critic-based. OMDb adds IMDb (audience) + Metacritic/RT (critics) cheaply. Enriching only the
shortlist keeps usage under OMDb's 1,000/day free limit; permanent caching makes repeat/shared films
free. **Graceful degradation:** no OMDb key → enrichment skipped, recs use TMDB-only quality (proven
by tests). Re-run @sthakkar: mean IMDb 7.0 / mean Metascore 63 across the top-20; well-reviewed titles
rose (Trainspotting 8.1/83, A Simple Plan 7.5/81, Blue Velvet 7.7/75, Talented Mr. Ripley 7.4/76).
**Affects:** SPEC §2 (stack), §4.2 (OMDb enrichment), §4.4 (review-blended quality); new
`backend/omdb.py`; `config.py`, `models.py` (`Film` review fields), `tmdb.py` (imdb_id),
`validate_recommender.py` (two-pass). Requires `OMDB_API_KEY` in `.env` (optional).
**Note / open lever:** taste still dominates (quality ≈ 1/6 of the score), so a strong taste-match but
poorly-reviewed film (e.g. Kiss the Girls, RT 35%) can still rank high. If desired, raise `w_quality`
or add a review floor — left as a tunable, not changed by default.
