# Constellation — Letterboxd ML Recommender · Build Spec

A deployed site where anyone enters a Letterboxd username and watches a recommender
build a navigable "map of their taste" out of their rated films, then surfaces new
films with visible, explainable reasoning.

The wow-moment is **crystallization**: a formless cloud of the user's posters snaps
into meaningful constellations. The lasting value is an explorable map where every
recommendation is connected, by glowing edges, to the films that earned it.

---

## 1. Goals & non-goals

**Goals**
- Any public Letterboxd username → a real, explainable recommender, rendered as a WebGL constellation.
- The visualization is *honest*: every visual element maps to a real step in the pipeline.
- Fully responsive (desktop + mobile WebGL).
- Stateless, shareable links: `/u/{username}`.

**Non-goals (v1)**
- No accounts, login, or saved profiles.
- No TV shows (films only).
- No two-user "blend" mode (candidate for v2).
- Not the official Letterboxd API — it explicitly excludes recommendation/analysis projects, so v1 scrapes public profiles. Accept the ToS-gray risk; mitigate with caching + polite rate-limiting.

---

## 2. Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | Python + FastAPI | Async (concurrent TMDB calls during scrape), Pydantic typed contracts |
| Scraping | letterboxdpy | Maintained; pulls films, ratings, likes, watchlist |
| Metadata | TMDB API v3/v4 (free) | Genres, credits, keywords, recommendations, similar |
| ML | scikit-learn, numpy, umap-learn | Feature vectors, cosine scoring, 2D projection |
| Cache | Redis | Keyed by username + TTL; scrape as rarely as possible |
| Frontend | TypeScript + React (Next.js) | Slots into shanethakkar.com toolchain |
| Render | deck.gl (primary), PixiJS (optional) | deck.gl scales to thousands of sprite nodes; PixiJS if the crystallization needs bespoke control |
| Backend host | Render / Railway / Fly | Long-running scrape jobs — NOT serverless (timeouts, cold starts) |
| Frontend host | Vercel | Standard Next.js |

---

## 3. Pipeline (the four acts)

Each act is a real backend phase **and** a frontend animation act, bound together over SSE
so the "watch it think" choreography is driven by actual progress, never faked.

1. **Scrape** — letterboxdpy pulls the user's films, star ratings, and likes. Each film page exposes its TMDB id, so we map Letterboxd → TMDB directly (no fuzzy title matching).
   *Frontend:* posters cascade in on a stream.
2. **Enrich** — concurrent TMDB calls (`append_to_response=credits,keywords,recommendations,similar`) hydrate each film with genres, director, top cast, keywords, decade, language, runtime.
   *Frontend:* posters drift into a chaotic point cloud.
3. **Embed** — build a feature vector per film; UMAP-project the combined watched+candidate matrix to 2D; compute kNN-cosine edges.
   *Frontend:* **crystallization** — the cloud settles into clusters. (Signature moment.)
4. **Score** — build the taste vector, score candidates, run MMR for diversity, attach "why" edges.
   *Frontend:* recommendations ignite at their cluster centers; explanation edges light up.

---

## 4. Backend modules

### 4.1 `scraper.py`
- Input: username. Output: list of `{tmdb_id, slug, title, year, rating?, liked?, in_watchlist?}`.
- Pull rated films, liked films, and watchlist (for exclusion). Handle private profiles gracefully (return a clear error the frontend can render).
- Be polite: concurrency cap, jittered delays, realistic User-Agent, retry/backoff on 429/403.

### 4.2 `tmdb.py`
- Async client (httpx). Single batched call per film via `append_to_response`.
- Extract: `genres[]`, `director`, `top_cast[5]`, `keywords[]`, `release_decade`, `original_language`, `runtime_bucket`, `poster_path`, `tmdb_recommendations[]`, `tmdb_similar[]`.
- Candidate pool = union of `recommendations`+`similar` for the user's top-rated films, plus an acclaimed/popular backfill from `discover`, minus everything already logged (watched + watchlist).

### 4.3 `features.py`
- Vector = concatenation of:
  - genres (multi-hot)
  - top-N directors / top-N cast (multi-hot, capped)
  - keywords (hashed or top-k, TF-IDF weighted so common keywords don't dominate)
  - decade (one-hot), language (one-hot), runtime bucket (one-hot)
- L2-normalize. Categorical sparsity → TF-IDF-style down-weighting of ubiquitous traits.

### 4.4 `recommender.py`
- **Taste vector** = weighted mean of watched-film vectors, weight = `(user_rating − user_mean_rating)`, with liked films given a positive bump. Films below the user's own average pull *negative*.
- **Candidate floor** = drop candidates below a TMDB vote-count floor (default 500) before scoring, so the map isn't full of films nobody has heard of. (Relaxed only if the pool would fall below `top_n`.)
- **Score** = blend of three **min-max-normalized** components so the weights are comparable: `w_content·cosine(candidate, taste)` + `w_graph·rec-graph-provenance` + `w_prior·mainstream_prior`. The **mainstream prior** = `w_quality·Bayesian-rating` (vote_average shrunk toward the pool mean by vote_count) + `w_popularity·log(vote_count)` + `w_recency·year`. Defaults lean mainstream (`content 0.55 / graph 0.15 / prior 0.45`) but keep taste in the lead; all weights + the floor are **per-request tunable knobs** (a later UI can expose mood / popularity / recency / genre-year filters).
- **Diversity** = MMR re-ranking so you don't get ten near-identical films.
- **"Why"** = each recommendation's top-k nearest **highly-rated** watched neighbors (only films rated at/above the user's average, or liked) — so "because you rated X" always points at a film the user actually liked. These become the explanation edges + `shared_traits`.
- **Sparse profiles** (<~8 ratings): shift weight onto the mainstream prior so the map still renders something meaningful and recognizable.

### 4.5 `projection.py`
- UMAP (`cosine` metric) fit on the combined watched+candidate feature matrix → 2D coords.
- Cluster (HDBSCAN or KMeans) for cluster ids; optional auto-labels from dominant genre/keyword (v2: an LLM can name clusters from their members).
- Edges: kNN on cosine similarity above a threshold; tag each edge's `shared` dimension (director / genre / keyword) — the strongest shared trait.

### 4.6 `cache.py`
- Redis. Key `rec:{username}`, value = full graph payload, TTL (e.g. 24h). `?refresh=true` busts it.
- Cache hit → return instantly; frontend fast-forwards the pipeline to the settled state.

---

## 5. API contract (Python → TypeScript)

Scraping can take minutes, so use an async job + SSE stream that also powers the animation.

```
POST /api/jobs            { "username": "shane" }  ->  { "job_id": "..." }
GET  /api/jobs/{id}/stream  (Server-Sent Events)
```

**SSE events** (drive the four acts):
```
event: phase
data: {"phase":"scraping","progress":0.4,"detail":"312 / 780 films"}

event: phase
data: {"phase":"enriching","progress":0.7}

event: phase
data: {"phase":"embedding"}

event: phase
data: {"phase":"scoring"}

event: result
data: { ...graph payload below... }
```

**Graph payload** (final `result` event; also what a cache hit returns directly):
```jsonc
{
  "username": "shane",
  "generated_at": "2026-06-22T18:00:00Z",
  "stats": { "rated": 412, "avg_rating": 3.6, "clusters": 6 },

  "nodes": [
    {
      "id": "tmdb:27205",
      "type": "watched",            // "watched" | "recommended"
      "title": "Inception",
      "year": 2010,
      "poster_url": "https://image.tmdb.org/t/p/w185/...",
      "x": 0.34, "y": -1.21,         // UMAP coords
      "cluster": 2,
      "rating": 4.5,                 // present if watched
      "score": null,                 // present if recommended
      "genres": ["science fiction","thriller"],
      "director": "Christopher Nolan"
    }
  ],

  "edges": [
    { "source": "tmdb:157336", "target": "tmdb:27205", "weight": 0.82, "shared": "director" }
  ],

  "recommendations": [
    {
      "id": "tmdb:49047",
      "title": "Prisoners",
      "score": 0.87,
      "because": [                   // the explanation edges / "why"
        { "id": "tmdb:27205", "title": "Inception",  "contribution": 0.41 },
        { "id": "tmdb:273481", "title": "Sicario",   "contribution": 0.33 }
      ],
      "shared_traits": ["dir. Villeneuve", "tense", "thriller"]
    }
  ],

  "clusters": [
    { "id": 2, "label": "cerebral sci-fi", "centroid": [0.30, -1.0] }
  ]
}
```

Notes: `id` is a stable `tmdb:{id}` string. Recommended nodes carry `score`; watched nodes carry `rating`. Edge `shared` ∈ {`director`,`genre`,`keyword`,`cast`}. `label` may be null in v1.

---

## 6. Frontend

### 6.1 Routes
- `/` — landing: username input, one-line pitch, a looping demo constellation.
- `/u/{username}` — kicks off (or reuses cached) job; renders pipeline → constellation.
- Empty/error states: private profile, user not found, too few ratings — each written as direction ("This profile is private — only public diaries can be mapped"), not a generic error.

### 6.2 Render layers (deck.gl)
- **Poster layer** — `IconLayer`/`BitmapLayer` of poster sprites at `(x,y)`; size ∝ rating (watched) or score (recommended).
- **Edge layer** — `LineLayer`; opacity ∝ weight; watched-watched edges hairline white; explanation edges amber when their recommendation is active.
- **Cluster layer** — soft hulls/labels behind posters (low opacity).
- Reach for **PixiJS** only if the crystallization tween needs more art-directed control than deck.gl transitions give.

### 6.3 The four-act choreography
1. **Scrape** — posters fade/stream in at random positions while `phase:scraping` progress ticks.
2. **Enrich** — posters jitter into a loose cloud; subtle depth/parallax.
3. **Embed (crystallization)** — animate each poster from cloud position → final UMAP `(x,y)` with eased, staggered transitions; clusters visibly form. Hold a half-second beat.
4. **Score** — recommended posters ignite at cluster centers; explanation edges draw outward to their seed films.

Respect `prefers-reduced-motion`: skip straight to the settled constellation.

### 6.4 Interaction model (the explorable map)
- **Hover/tap a node** → highlight it + its neighbors; dim the rest; show title/year/rating-or-score.
- **Hover/tap a recommendation** → its `because` edges glow amber; side panel shows `shared_traits` + the seed films ("Because you rated Inception, Sicario highly").
- **Click** → detail panel (poster, synopsis, TMDB link, "add to Letterboxd watchlist" deep link).
- **Zoom/pan** the map; **filter** by cluster or genre; **toggle** watched-only / recommended-only.
- **Share** → copies `/u/{username}`.

### 6.5 Responsive (fully WebGL everywhere)
- Desktop: full node count, hover interactions.
- Mobile: same WebGL canvas, but cap rendered node count (e.g. top-N watched by rating + recommendations), tap replaces hover, simplified edge density, larger hit targets. Pinch-zoom/pan native.
- Quality floor: visible keyboard focus, reduced-motion honored, graceful degrade to a ranked list if WebGL is unavailable.

### 6.6 Design tokens
Monochrome shell so the **posters supply the color**; one functional accent for "why".

```
--void:        #08090B   /* near-black background, faint cool undertone */
--panel:       #121317   /* raised surfaces, detail drawer */
--leader:      #F2F0EA   /* warm film-leader white — primary text/UI */
--dim:         #8A8A93   /* secondary text, inactive labels */
--beam:        #E8C36A   /* projector-amber — ONLY active node halo + explanation edges */
```
- **Edges encode meaning by form, not rainbow:** white hairline = baseline similarity; weight/opacity ∝ strength; solid vs. dashed can distinguish director vs. genre. Amber is reserved strictly for the active explanation.
- **Type (recommendation, swappable):** Display = Space Grotesk (or a condensed grotesque); Body = Inter; Data/utility = JetBrains Mono (for counts, similarity %, ratings). Make the data-mono a deliberate, visible part of the identity.
- **Motion:** crystallization is the one orchestrated moment; keep everything else quiet.

---

## 7. Build order (phased for Cursor)

**Phase 0 — Backend skeleton**
- FastAPI app, Redis wired, TMDB client with a couple of films end-to-end. Validate TMDB key + id mapping.

**Phase 1 — Recommender (no UI)**
- Scraper → features → taste vector → scored recs. Test against your own profile; sanity-check the picks. This is the part that must be *correct* before anything is pretty.

**Phase 2 — Projection + payload**
- UMAP coords, clusters, edges; assemble the full graph payload. Serialize and eyeball the JSON.

**Phase 3 — Static constellation (the real core)**
- Next.js + deck.gl renders the settled map from the payload: posters, edges, hover, detail panel, filters. Ship this — it's genuinely useful on its own.

**Phase 4 — SSE + pipeline intro (enhancement)**
- Job endpoint + SSE; bind the four-act animation to phase events; build the crystallization tween. If time runs out, the static map already works — the intro is a flourish, not a dependency.

**Phase 5 — Polish + deploy**
- Mobile tuning, reduced-motion, error states, share links. Backend → Render/Railway/Fly; frontend → Vercel.

---

## 8. Risks & mitigations
- **Scraping blocked from cloud IPs** → aggressive Redis caching, polite rate-limiting, backoff; residential proxy only if needed.
- **Scrape latency** (~1.2 films/s) → async job + cache; the pipeline animation makes the wait feel intentional.
- **TMDB matching misses** → use the TMDB id off the Letterboxd film page; skip + log unmatched.
- **Sparse profiles** → genre/popularity fallback so the map never renders empty.
- **Mobile WebGL perf** → node-count cap, simplified edges, sprite atlas for posters.
- **Crystallization jank with many nodes** → precompute coords server-side; animate interpolation only; never run UMAP in the browser.

---

## 9. Deferred (v2+)
- LLM-named clusters ("cerebral sci-fi", "cozy melancholy").
- Two-user "blend" mode (shared constellation, intersection recs).
- CSV-export upload path (fully ToS-clean alternative to scraping).
- "Why not" — show what's pulling a film *away* from your taste.

---

## 10. Claude Code workflow & repo documentation

Build this in Claude Code one **phase per session** (see §7). Each session: `/clear`,
enter **Plan Mode** (Shift+Tab) and have Claude read `SPEC.md` + `PROGRESS.md` and
produce a plan; review/edit it; approve; implement; verify with evidence; update docs; commit.

Four docs carry the project's memory:
- **SPEC.md** — *what* we're building (this file; the plan of record).
- **PROGRESS.md** — *where* we are (living checklist + findings; updated every step).
- **DECISIONS.md** — *why* it changed (append-only log).
- **CLAUDE.md** — *how* Claude should behave (loaded every session).

### 10.1 `CLAUDE.md`
Create this at the repo root. Keep it under ~200 lines.

````md
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

## Commands
- Backend deps: `pip install -r backend/requirements.txt`
- Run backend: `uvicorn backend.app:app --reload`
- Backend tests: `pytest -q`
- Lint/format (Python): `ruff check . && ruff format .`
- Frontend dev: `cd frontend && npm run dev`
- Frontend typecheck/lint: `npm run typecheck && npm run lint`
- Build frontend: `npm run build`

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

## Where things live
- `backend/` — scraper, tmdb, features, recommender, projection, cache, app (FastAPI).
- `frontend/` — Next.js app; `/u/[username]` route; deck.gl render layers.
- `SPEC.md` (what) · `PROGRESS.md` (where) · `DECISIONS.md` (why) · this file (how).
````

### 10.2 `PROGRESS.md` (template Claude maintains)
Updated after every step. Living source of truth for status.

````md
# Progress

_Last updated: <date> · Current phase: <N — name>_

## Phase 0 — Backend skeleton
- [x] FastAPI app boots, Redis wired
  - Finding: <e.g. TMDB id is on the film page as data-tmdb-id; mapping confirmed>
- [ ] TMDB client validated end-to-end on 2 films
- Next: <next concrete action>

## Phase 1 — Recommender (no UI)
- [ ] Scraper -> features -> taste vector -> scored recs
- [ ] Validated against my own profile (recs gut-checked)
...

## Open loops / blockers
- <anything waiting on a decision or external thing>
````

### 10.3 `DECISIONS.md` (template, append-only)
One entry whenever the design changes from SPEC.

````md
# Decision Log

## 2026-06-22 - Candidate pool source
**Decision:** Use TMDB recommendations + similar (top-rated seeds) + acclaimed backfill.
**Why:** No standing multi-user corpus, so a content-based hybrid avoids cold-start.
**Affects:** SPEC 4.2, 4.4.

## <date> - <short title>
**Decision:** ...
**Why:** ...
**Affects:** <SPEC sections / files>
````
