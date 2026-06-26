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

## 2026-06-25 — Eval harness + budgeted scrape; multi-centroid kept opt-in
**Decision:** (1) Add a leave-one-out eval harness (`backend/evaluate.py`, SPEC §4.7) reporting
pool-recall@N and recall@K. (2) Budget the scrape: pull the full rating list (exact mean) but resolve
`slug→tmdb_id` only for the top-`resolve_top`(200) + bottom-`resolve_bottom`(100) rated + likes +
watchlist; seeds are dynamic (all ≥4★ up to `SEED_MAX`=150, was fixed 40). (3) Add multi-centroid
taste (`n_clusters`) but **default to single-centroid** — the harness showed no gain.
**Why:** User wanted higher accuracy + dynamic seeds without scraping thousands of films for huge
profiles. The budget is principled (skipped films are near-mean → taste-weight ≈ 0) and turns a
~30-min scrape into ~2 min. The harness made "more accurate" measurable. **Key finding (@sthakkar):**
pool-recall ≈ **13%** — ~87% of held-out favourites aren't even reachable in the candidate pool, so
**candidate recall, not the taste model, is the ceiling**; multi-centroid (k=5) matched/under-performed
k=1, so it's opt-in pending recall work. Decision driven by evidence, not intuition.
**Affects:** SPEC §4.1 (budgeted scrape), §4.4 (opt-in facets), new §4.7 (evaluation); new
`backend/evaluate.py`; `scraper.py` (budget), `recommender.py` (taste_centroids/content_scores,
`n_clusters`), `validate_recommender.py` (SEED_MAX). **Next accuracy lever:** widen candidate recall
(deeper/2-hop TMDB graph, larger candidate cap, taste-filtered discover) — Tier 2.

## 2026-06-25 — Widen candidate recall: 2-hop expansion + raised cap
**Decision:** Add `TMDBClient.grow_candidate_pool` (shared by validate + evaluate): build the 1-hop
pool (seeds' recs/similar + discover), then **expand a 2nd hop** from the strongest hop-1 candidates
(recs-of-recs), capped at ~1500 (was 500/600). 2-hop hits enter at half provenance weight. A `memo`
param shares enrichment across eval splits.
**Why:** The harness proved candidate recall — not ranking — was the ceiling (pool-recall 13%). This is
the directly-indicated fix. **Result (@sthakkar, measured): pool-recall 13%→25.9%, recall@20
9.3%→20.4%** (≈2×); recall@100 ≈ pool-recall, so ranking is sound and breadth is the remaining lever.
Real recs didn't regress (surfaced strong new matches: Donnie Brasco←GoodFellas/Departed, Brick←Knives
Out, Gangs of New York, Lost Highway←Mulholland Drive).
**Affects:** SPEC §4.2 (2-hop pool) + §4.7 (result); `backend/tmdb.py` (`grow_candidate_pool`),
`validate_recommender.py` + `evaluate.py` (use it; removed duplicated pool code). **Further recall
levers (later):** 3-hop, taste-filtered discover, true collaborative filtering.

## 2026-06-25 — Recall round 2: taste-discover + TMDB caching + cap 500→3000
**Decision:** Add (1) **taste-filtered discover** (`discover_by_genres`: well-voted films in the user's
top genres) as a 3rd candidate source; (2) **Redis caching of `get_movie`** responses (30-day TTL),
threaded via `create_tmdb_client(http, redis)`; (3) raise the candidate cap **1500→3000**.
**Why:** Chasing the recall ceiling the harness exposed. Findings (measured, @sthakkar): taste-discover
alone gave **no** gain at cap 1500 — the cap was saturating and discarding reachable-but-weakly-connected
favourites. Raising the cap to 3000 took **pool-recall 26%→74%, recall@20 20%→31%** (vs 13%/9% at the
very start), and rec *quality improved* (surfaced Layer Cake, Crooked House←Knives Out, The Night of the
Hunter (Meta 97), Donnie Brasco). So the cap — not the source mix — was the dominant lever; all three
sources contribute once they fit. Caching is a production win (shared films across users/re-runs).
**Cost:** up to ~3000 TMDB enrich calls per cold scrape (~1 min); amortized by caching in production
(locally fakeredis is per-process so each run is cold). Remaining ~26% unreachable ≈ taste "islands" →
collaborative filtering is the only bigger lever (deferred, large lift).
**Affects:** SPEC §4.2 (3 sources, cap, caching) + §4.7 (result); `backend/tmdb.py`
(`discover_by_genres`, genre map, get_movie cache, cap default), `app.py`/`validate_recommender.py`/
`evaluate.py` (pass redis to `create_tmdb_client`).

## 2026-06-25 — Phase 2: projection + graph payload (KMeans, distinctive labels, displayed-set)
**Decision:** `backend/projection.py` (UMAP cosine → 2D, KMeans clustering, lift-based genre labels,
kNN edges) + `backend/graph.py` (`build_graph` → the SPEC §5 payload, cached `rec:{username}` 24h) +
`backend/validate_graph.py`. Three refinements of SPEC §4.5, all evidence-driven:
1. **Project the displayed set** (watched + top-N recs, ~250), not the 3000-film pool (a meaningless cloud).
2. **KMeans, not HDBSCAN** — HDBSCAN lumped @sthakkar's concentrated crime/thriller taste into one
   230-node "drama" mega-blob; KMeans gives ~7 legible regions every poster belongs to.
3. **Lift-based labels** — raw dominant genre made every cluster "drama"; lift (cluster share ÷ global
   share) surfaces the distinctive genres ("mystery · crime", "western · history").
**Why:** Phase 2 turns the recommender output into the navigable map data the frontend renders.
UMAP runs server-side only (guardrail). Validated @sthakkar: 267 nodes (217 watched + 50 rec), 7
labelled clusters, 142 edges, cache hit on 2nd build; JSON eyeballed.
**Affects:** SPEC §4.5 (rewritten); new `projection.py`/`graph.py`/`validate_graph.py`; `models.py`
(Node/Edge/Cluster/Stats/GraphPayload mirroring SPEC §5); `requirements.txt` (umap-learn + numba≥0.60
pin — uv otherwise resolved a pre-3.12 numba). Edge threshold (0.15) + cluster count are tunable in Phase 3.

## 2026-06-25 — Phase 3: static constellation (Next.js 16 + deck.gl)
**Decision:** Ship the settled WebGL map. Backend: `GET /api/graph/{username}` (cache-first
`build_graph`; `?refresh`) + CORS + domain-error→HTTP mapping. Frontend (`frontend/`): Next.js 16
App Router + TS strict + Tailwind v4 + deck.gl `OrthographicView` — poster `IconLayer`, similarity
`LineLayer`, cluster `TextLayer`; landing, `/u/[username]`, detail drawer, filters (cluster/genre +
watched/recs toggles), share, loading/error states, and a WebGL-unavailable → ranked-list fallback.
**Notable choices:**
- **Phase 3 uses a synchronous `GET /api/graph`, not the SPEC §5 POST-job + SSE flow** — that async
  "four-act" streaming experience is Phase 4. Cold builds block (~90s); warm cache is instant.
- **Fonts:** honoured SPEC §6.6's Space Grotesk / Inter / JetBrains Mono even though the `frontend-design`
  skill steers away from them — the SPEC is the approved plan of record and marks type "swappable"; the
  real signature is the monochrome-with-amber-only palette + the mono-data identity.
- **Poster atlas at w92, not w185:** deck.gl auto-packs all poster icons into one texture; w185 overflowed
  software-GL limits (and is wasteful at ~30–50px on screen). w92 thumbnails in the IconLayer (full-res
  kept for the detail drawer) — lighter atlas, faster load (a `fixing-motion-performance` win).
- Next.js **16** (newer than training data) — read its bundled docs per `frontend/AGENTS.md`; `params`
  is now a Promise (awaited in the server route); the new `react-hooks/set-state-in-effect` lint rule
  pushed state-reset via a remount `key` instead of in-effect setState.
**Why:** SPEC §7 calls the static map "the real core … genuinely useful on its own." Verified via
Playwright: landing, 267-poster constellation, select→detail+amber-halo+dim, cluster filtering; prod
`next build` clean.
**Affects:** SPEC §5 (GET endpoint now; POST/SSE deferred to Phase 4) + §6 (implemented); `backend/app.py`
(endpoint+CORS), `backend/config.py` (`frontend_origin`); entire `frontend/`. Deferred to Phase 5:
landing demo loop, mobile node-cap/touch, reduced-motion depth, keyboard-focus a11y, URL-encoded filters.

## 2026-06-26 — Phase 3.5: recommendation-first map + crystallization reveal
**Decision:** Reframe the constellation around the *recommendations* (user feedback: "I don't need to
map every movie; I wanted the constellation to visualize the recs, and an easy way to see which are
recommended"). Three changes:
1. **Backend payload** (`graph.py`): nodes = the recs + only their `because` seed films (~50 + ~50),
   not all 217 watched. The recommender still uses all watched internally; the *displayed* set is just
   recs + the films that earned them. (@sthakkar: 267 → 120 nodes.)
2. **Recs-first map** (`Constellation.tsx`): recommendations are larger posters with a persistent amber
   ring (the "stars"); seed films are small/dim context. A **`RecRail`** (ranked list like
   `recommendations-sthakkar.md`) docks right and expands to a full list-view overlay; clicking a rec
   flies the camera to it (`LinearInterpolator`) and lights its amber "why" edges. Detail drawer moved left.
3. **Crystallization reveal:** on load, posters start as a scattered cloud and settle into the UMAP
   clusters via deck.gl `getPosition` transitions (ease-out `1−2^(−10t)`, ~1.4s); edges/labels appear
   only after settle (clean reveal); honours `prefers-reduced-motion`. Applied `emil-design-eng` (rare
   orchestrated moment → ease-out, move-from-visible-cloud not from nothing) + `fixing-motion-performance`
   (GPU attribute transitions, w92 atlas).
**Why:** Makes the payoff (recs) the unmistakable subject + trivially scannable, keeps the wow.
Verified via Playwright: recs-first settled map, mid-crystallization frame, rail→fly-to+why-edges,
expanded list. tsc+lint+`next build` clean; 44 backend tests pass.
**Affects:** SPEC §6 (note) + §5 (payload node set is now recs+seeds); `graph.py`, `test_graph.py`;
`Constellation.tsx`, new `RecRail.tsx`, `ConstellationView.tsx`, `DetailPanel.tsx`. SSE-bound four-act
still Phase 4.
**Follow-up (posters too small / couldn't zoom in):** glyphs were `sizeUnits:"pixels"`, so zoom only
spread nodes apart — it never magnified posters. Switched poster/ring/halo to **world units**
(`sizeUnits:"common"` + `sizeScale = span/620` to keep the default look, + min/max pixel clamps) so
zoom now enlarges posters; bumped source thumbnails w92→w154 (crisp when large), raised `maxZoom`
8→11, and added hover-to-enlarge (`getSize` ×1.7 on hover, 160ms). Verified via Playwright zoom test.

## 2026-06-26 — Pivot: the recommendations TABLE is the product; constellation = reveal + opt-in explore
**Decision:** After using it, the user judged the constellation "more wow than useful" and asked to make
the recommendations themselves front-and-centre. So:
1. **A ranked recommendations table** (poster-forward **card-list**) becomes the primary surface:
   poster, title/year, match score, **IMDb/Metacritic/Rotten Tomatoes**, director, runtime, genres, the
   **"because you rated …"** (foregrounded in amber — our differentiator), shared traits, and TMDB +
   Letterboxd (`/tmdb/{id}`) links. **Sortable** (match/IMDb/Meta/year/A–Z) + **genre filter**.
2. **Backend:** enrich the `Recommendation` payload with genres/director/runtime/poster + IMDb/Meta/RT —
   data we already computed (OMDb) but were discarding before serialization. (`models.py`,
   `recommender.py`, `types.ts`.)
3. **Constellation demoted** to (a) the crystallization **reveal** on load that **auto-hands off** to the
   table (~2.8s), and (b) an **opt-in "Explore the constellation"** interactive mode (with a "←
   Recommendations" back button). `Constellation` gained an `animate` flag (crystallize on reveal,
   instant in explore); removed the grey backing-dot circles under posters (user request). The table is
   also the **no-WebGL fallback** (deleted `RankedList.tsx`).
**Why:** The genuine value is a great, scannable, *explainable* recommendations list; the map is a
beautiful flourish, not the tool. This keeps the craft (reveal + explore) while putting the useful
artifact first. Verified via Playwright: reveal → table → explore.
**Affects:** SPEC §6 (rewritten note); `backend/models.py` + `recommender.py` (Recommendation fields);
`frontend`: new `RecommendationsTable.tsx`, `ConstellationView.tsx` (reveal/table/explore modes),
`Constellation.tsx` (animate prop, no dots), `types.ts`, deleted `RankedList.tsx`. **Still Phase 4:**
streaming the reveal during the real build over SSE. Possible later tweak: drop the amber rec rings too.

## 2026-06-26 — Phase 3.7: liquid-glass handoff — the constellation recedes, recs ride on glass
**Decision:** The user proposed (and a static prototype at `/glass-proto` confirmed) unifying the two
surfaces instead of swapping between them: the constellation **recedes into a defocused bokeh background**
and the recommendations float above it on warm frosted **"liquid glass."** Flow is now **reveal → recede →
glass ↔ explore**:
1. **Reveal** crystallizes the map sharp (unchanged), then the *same* canvas **recedes** — a ~0.9s CSS
   blur-out (`blur(0→22px)` + `scale(1.06)` + fade) — while the glass console rises over it. Once the
   recede finishes the **WebGL canvas unmounts**.
2. **Glass** (steady state): `RecommendationsConsole` (the card-list, now on a `.glass` console) over
   `GlassBackground` (a `fixed`, blurred, slowly-drifting poster bokeh field + projector beams + scrim).
3. **Explore** still brings the live interactive map forward, with a back button.
**Why:** It resolves the wow-vs-utility tension — you *feel* the map without it competing with the recs —
and stops discarding the crystallized constellation. **Perf guardrail (fixing-motion-performance):** never
run live WebGL behind a `backdrop-filter`; the recede is a brief blur-out, then the steady-state background
is a cheap **static** `<img>` bokeh field that `backdrop-filter` samples. **Craft (emil-design-eng):** one
`Constellation` instance is kept mounted across reveal→recede (keyed, never remounts → no re-crystallize),
and blur masks the swap to the bokeh so it reads as one continuous defocus. `prefers-reduced-motion` →
straight to glass, no recede/drift.
**Affects:** SPEC §6 (note revised); `frontend`: new `GlassBackground.tsx` + `RecommendationsConsole.tsx`,
`ConstellationView.tsx` (reveal/glass/explore + `recedeCanvas`), `globals.css` (`.glass`/`.bokeh`/
`.glass-card` promoted from the prototype + `constellation-recede` keyframes); deleted
`RecommendationsTable.tsx` and the `/glass-proto` prototype route. `Constellation.tsx` unchanged (the
recede is a CSS wrapper). Verified via Playwright: reveal → recede → glass → explore → back, plus a
reduced-motion run, all with zero page errors. **Still Phase 4:** binding the reveal to real build progress
over SSE; optionally snapshotting the actual crystallized canvas as the bokeh for exact position continuity.

## 2026-06-26 — Phase 3.8: explore map is a node-link constellation (dots), not a poster wall
**Decision:** The user found the explore map "still cluttered… hard to see the actual constellation" — the
poster sprites are big opaque rectangles that hide the edges and cluster structure (ironic for a thing called
"Constellation"). So `Constellation` gains a **`variant` prop**: `"posters"` (the reveal spectacle, unchanged)
vs **`"dots"`** (explore). In dots mode:
- Nodes are **dots coloured by taste cluster** (`CLUSTER_COLORS` — a muted 6-hue palette; colour now *encodes*
  which region of taste a film sits in). Recommendations are **larger, brighter dots inside the amber ring with
  a soft amber glow** — the unmistakable stars.
- **Titles sit under the dots**: recs always; every node once you **zoom in** past a threshold; plus whatever's
  hovered (progressive disclosure — labelling all ~100 at once is worse clutter than the posters).
- The **poster blooms in on hover** (an `IconLayer` for just the hovered node), so richness is on-demand and
  the structure stays clean. `pickingRadius={8}` on the deck so the small dots are easy to hover/click.
- **Edges + cluster labels turned up** (they were tuned faint to survive *under* posters; now they carry the
  structure).
**Why:** A node-link map of dots + lines is what a constellation actually is — it makes the clusters and the
"why" connections legible, declutters the view, is truer to the metaphor, and is cheaper than a poster atlas
(no per-node textures; fixing-motion-performance). Posters aren't lost — they live in the glass console, the
rail, and the hover bloom. This **amends the SPEC §6.6 "posters supply all the colour, shell is monochrome"
tenet**: the explore map now uses cluster colour as a meaningful encoding; amber stays reserved for recs/"why";
the rest of the shell stays monochrome.
**Affects:** SPEC §6 note + §6.6 amendment; `frontend/components/Constellation.tsx` (`variant` prop,
`CLUSTER_COLORS`, dot/glow/hover-poster/title layers, brighter edges/labels, `pickingRadius`),
`ConstellationView.tsx` (explore passes `variant="dots"`; Legend copy → "colour = a region of your taste ·
hover for the poster"). Reveal still uses `variant="posters"`. Verified via Playwright: dots map renders with
visible cluster structure, hover blooms the poster, zoom-in reveals all titles — zero page errors; tsc + lint
+ build clean. **Easy follow-ups if wanted:** cluster-colour swatches in the genre/cluster Filters; tuning ring
density; making the reveal dots too (currently kept as posters for the wow).

## 2026-06-26 — Phase 3.8a: dots tuning + the real edge fix (constellation was barely connected)
**Decision:** Acting on user feedback that the dots map was "still cluttered… lines very hard to see… cluster
labels blocked": (1) **shrank the dots** — rec dots `0.36→0.18`, seed dots `0.24→0.14`, and the amber rec
**rings are now variant-aware** (`0.62→0.30`, max px `210→46`) so recs are small stars, not big circles;
(2) **brightened/thickened edges** in dots mode (at-rest alpha `~24+w·110 → 52+w·150`); (3) moved the
**cluster labels to render on top** with a dark backing pill + bigger bold caps so dots/titles can't block
them, and lightened the film-title pills. **But the real cause of "hard to see how things connect" was the
data:** the graph had only **19 edges for 117 nodes**. `similarity_edges` filtered kNN pairs at an absolute
`threshold=0.15`, and these sparse TF-IDF vectors are near-orthogonal, so almost everything was cut. Fixed by
**always keeping each node's single nearest neighbour** (guarantees a connected web, no orphan dots) plus a
lowered `threshold=0.08` for the rest → **260 edges, 0 isolated nodes**.
**Why:** Small dots + a genuinely connected, visible web is what makes it read as a constellation; the
nearest-neighbour floor is robust to the feature space being sparse (a fixed absolute threshold is not).
**Affects:** `backend/projection.py` (`similarity_edges`: nearest-neighbour floor + `threshold 0.15→0.08`;
44 tests still pass), `frontend/components/Constellation.tsx` (dot/ring/glow sizes, edge alpha/width, cluster
labels on top + pill, lighter title pills). Required a backend restart + cache rebuild (`?refresh=true`).
Verified via Playwright: connected web with smaller dots + readable region labels, hover-poster + zoom labels
intact — zero page errors; backend ruff + 44 tests, frontend tsc + lint + build all clean.

## 2026-06-26 — Phase 4: streamed build — real posters cascade in, then crystallize (SSE)
**Decision:** Turn the multi-minute cold build into a "watch it think" experience bound to real progress.
The build now streams over SSE; the user's **actual film posters cascade in** during enrichment, then
**crystallize** into the constellation when the layout is ready. Concretely:
- **`GET /api/graph/{username}/stream`** (single GET SSE via `sse-starlette`), **not** the SPEC's original
  `POST /api/jobs` + `GET /api/jobs/{id}/stream`. The browser consumes it with `fetch` + `ReadableStream`
  (abortable, **no** auto-reconnect — a reconnect would restart the build), so there's no job id and no
  multi-subscriber registry: the Redis cache already dedupes repeat builds (**KISS**). A cache hit emits
  `result` immediately.
- Events: `phase` (scraping→enriching→scoring→embedding) · `nodes` (a batch of enriched watched films as
  they resolve — the cascade source) · `result` (full payload) · `error` (domain errors; the SSE is 200).
- `build_graph` gained an optional async `emit` callback (default `None` = the byte-for-byte synchronous
  build). Watched enrichment is now **incremental** (`tmdb.stream_movies`, `asyncio.as_completed`) so
  posters stream as they resolve; the CPU-bound embed block runs in **`asyncio.to_thread`** so queued
  events actually flush while UMAP runs.
- Frontend: `RevealStream.tsx` owns sprite positions across cascade→crystallize for continuity (cloud →
  final UMAP coords in one zoom-0 view; recs settle in, non-displayed watched fade out). A live **phase
  intro** overlay replaces the spinner.
**Why:** The wait *is* the product moment — seeing your own diary stream in and resolve into a taste map
is the payoff. Single-GET-SSE is the least machinery that delivers it; the cache makes a registry
unnecessary.
**Gotcha fixed:** `sse-starlette` emits **CRLF** (`\r\n`) line endings; the first SSE parser split on
`\n\n` and silently never matched a boundary → "stream ended before ready." Parser is now CRLF-robust
(`/\r\n\r\n|\n\n|\r\r/`). Confirmed at the byte level (`event: result\r\n…`).
**Affects:** `backend/`: new `jobs.py` (`stream_build`), `graph.py` (`emit` + incremental enrich +
`to_thread`), `tmdb.py` (`stream_movies`), `app.py` (stream endpoint), `requirements.txt` (`sse-starlette`).
`frontend/`: new `lib/stream.ts` + `components/RevealStream.tsx` + `lib/poster.ts`, rewired
`ConstellationView.tsx` (stream + phase intro). 46 backend tests (2 new stream tests) pass; frontend tsc +
lint + build clean. Verified via Playwright on a real cold build: posters cascade (~150 in the cloud) →
crystallize → recede → glass → explore, zero page errors.
**Known dev-only quirk:** React StrictMode double-invokes the effect, starting two builds (the first is
aborted, which cancels its server-side task). Production (no StrictMode) starts one. Not worth dedup yet.
**Still later (Phase 5):** multi-subscriber registry / cross-tab dedupe; streaming candidate-pool posters;
finer scrape progress; deploy.
