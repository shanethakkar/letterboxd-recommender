# Progress

_Last updated: 2026-06-26 · Phase 3.8 (dots constellation) complete — next is Phase 4 (SSE + four-act pipeline animation)_

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
- [x] **Tuning pass (per user feedback): bias toward mainstream + rating-aware "why"**
  - Recs were too obscure/old. Added a TMDB vote-count floor (default 500), replaced the weak
    popularity prior with a composite mainstream prior (Bayesian quality + popularity + recency),
    normalized all score components, and restricted explanations to films rated ≥ the user's avg.
    All knobs are per-request params (ready for future UI filters). See DECISIONS + SPEC §4.4.
  - Evidence: re-run median TMDB votes 3,256 (was obscure), mean year 2004; recognizable on-taste
    titles (Trainspotting, Once Upon a Time in America, Cape Fear, Blue Velvet, Inside Man, The
    Killer). 20 tests pass, ruff clean.
- [x] **Review scores (per user feedback): IMDb + Metacritic via OMDb**
  - New `backend/omdb.py` enriches the top ~120 contenders with IMDb/Metacritic/RT (cached
    permanently); quality term now blends TMDB + IMDb + Metascore. Two-pass orchestration
    (pass-1 λ=1 shortlist → OMDb enrich → pass-2). Graceful no-key fallback (TMDB-only).
  - Evidence: re-run top-20 mean IMDb 7.0 / mean Metascore 63; well-reviewed titles rose
    (Trainspotting 8.1/83, A Simple Plan 7.5/81, Blue Velvet 7.7/75). 27 tests pass, ruff clean.
  - Known lever: taste still dominates (~1/6 weight on quality) so a strong-match-but-poorly-
    reviewed film can still rank high; raise `w_quality` / add a review floor if wanted.
- [x] **Accuracy work: eval harness + budgeted scrape + opt-in taste facets**
  - `evaluate.py` (SPEC §4.7): leave-one-out pool-recall@N + recall@K → accuracy is now a number.
  - Budgeted scrape (scraper.py): resolve only top-200/bottom-100 rated + likes/watchlist → huge
    profiles stay fast; dynamic seeds (≥4★ up to 150, was 40).
  - Multi-centroid taste (recommender `n_clusters`) added but **default off** — see finding.
  - **Finding (@sthakkar, evidence): pool-recall ≈ 13%** → candidate recall is the ceiling, not the
    ranking model; multi-centroid (k=5) showed no gain vs k=1. 32 tests pass, ruff clean.
  - Next accuracy lever (Tier 2): widen candidate recall (2-hop TMDB graph, larger cap, taste-filtered
    discover) — now measurable via the harness.
- [x] **Recall work: 2-hop candidate expansion + raised cap (`grow_candidate_pool`)**
  - Shared pool builder (validate + evaluate): 1-hop seeds' recs/similar → 2nd hop from strongest
    candidates → cap ~1500 (was 500/600). `memo` shares enrichment across eval splits.
  - **Measured win: pool-recall 13%→25.9%, recall@20 9.3%→20.4% (≈2×)**; recall@100 ≈ pool-recall
    (ranking sound, breadth is the remaining lever). Real recs didn't regress (Donnie Brasco, Brick←
    Knives Out, Gangs of New York surfaced). 33 tests pass, ruff clean.
  - Further recall levers (later): 3-hop, taste-filtered discover, true collaborative filtering.
- [x] **Recall round 2: taste-discover + TMDB caching + cap 500→3000**
  - Added taste-filtered discover (`discover_by_genres`, 3rd candidate source) + Redis `get_movie`
    caching (30-day TTL). Then found (harness) the **candidate cap was the dominant constraint**:
    taste-discover gave 0 gain at cap 1500, but raising the cap to 3000 unlocked everything.
  - **Measured: pool-recall 26%→74%, recall@20 20%→31%** (vs 13%/9% at the start). Rec quality
    improved too (Layer Cake, Crooked House←Knives Out, The Night of the Hunter Meta 97, Donnie Brasco).
    36 tests pass, ruff clean.
  - Cost: ~3000 TMDB enrich calls per cold scrape (~1 min), amortized by caching in prod. Remaining
    ~26% are taste "islands" → only collaborative filtering would push further (deferred, big lift).
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

## Phase 2 — Projection + payload — COMPLETE
- [x] `projection.py` — UMAP (cosine) 2D coords (server-side), KMeans clustering, lift-based
      distinctive genre labels, kNN similarity edges (deduped, shared-trait tagged).
- [x] `graph.py` `build_graph` — assembles the full SPEC §5 payload (nodes/edges/recommendations/
      clusters/stats), cached `rec:{username}` 24h; `models.py` has the §5 contract models.
- [x] `validate_graph.py` — serialize + eyeball JSON. 41 tests pass, ruff clean.
- [x] **Eyeballed @sthakkar**: 267 nodes (217 watched + 50 rec), **7 legible clusters**
      (mystery·crime, western·history, horror·thriller, romance·comedy, action·science fiction,
      animation·family, fantasy·adventure), 142 edges, cache hit on 2nd build.
  - Findings: project the *displayed set* not the 3000-pool; KMeans beats HDBSCAN here (concentrated
    taste → one mega-blob); lift-based labels avoid "drama" everywhere. See DECISIONS.
- Next: Phase 3 — Next.js + deck.gl renders the settled map from the payload (posters, edges, hover,
  detail panel, filters). The static constellation is the real core; ship it standalone.

## Phase 3 — Static constellation — COMPLETE
- [x] Backend `GET /api/graph/{username}` (cache-first) + CORS + domain-error→HTTP mapping.
- [x] Next.js 16 + deck.gl frontend (`frontend/`): landing, `/u/[username]`, deck.gl
      `OrthographicView` (poster IconLayer + similarity LineLayer + cluster TextLayer),
      detail drawer, filters (cluster/genre + watched/recs toggles), share, states,
      WebGL-degrade ranked list. Monochrome shell per §6.6 (Space Grotesk/Inter/JetBrains Mono).
- [x] **Verified (Playwright screenshots)**: landing; 267-poster constellation renders; click →
      select + amber halo + detail panel + dim-others; cluster filter isolates a region.
      `npx tsc --noEmit` + `npm run lint` clean; `next build` succeeds; 44 backend tests pass.
  - Findings: Phase 3 uses a synchronous GET (POST-job+SSE is Phase 4); deck.gl icon atlas needs
    small (w92) thumbnails; Next 16 has breaking changes (Promise `params`, set-state-in-effect lint).
    See DECISIONS.
- [x] **Phase 3.5 — recommendation-first map + crystallization (user feedback)**
  - Payload (`graph.py`) now = recs + only their `because` seed films (267 → 120 nodes for @sthakkar);
    recommender still uses all watched internally.
  - Recs-first map: recs = bright amber-ringed "stars", seeds = dim context. `RecRail` (ranked list
    like the .md) docks right + expands to a full list view; click a rec → fly-to + amber "why" edges.
  - **Crystallization reveal** on load (poster cloud → settled clusters, ease-out ~1.4s, edges after
    settle, reduced-motion aware). Applied emil-design-eng + fixing-motion-performance.
  - Verified (Playwright): settled recs-first map, mid-crystallization, rail→fly-to+why-edges, expanded
    list. tsc+lint+build clean; 44 backend tests pass.
- [x] **Phase 3.6 pivot — recommendations table is the product (user feedback)**
  - Enriched `Recommendation` payload (genres, director, runtime, poster, IMDb/Meta/RT — already
    computed, now serialized). New `RecommendationsTable` card-list: sortable (match/IMDb/Meta/year) +
    genre filter, review badges, **"because you rated…"** in amber, TMDB + Letterboxd links.
  - Constellation demoted to: crystallization **reveal** on load (auto-hands off to the table ~2.8s) +
    an opt-in **"Explore the constellation"** mode (back button). `animate` flag; removed grey backing
    circles. Table is also the no-WebGL fallback (deleted RankedList).
  - Verified (Playwright): reveal → table → explore. tsc+lint+build clean; 44 backend tests pass.
- [x] **Phase 3.7 — liquid-glass handoff: the constellation recedes, recs ride on glass**
  - User brainstorm → static prototype (`/glass-proto`) approved → wired into the app. The recs now sit on
    a warm frosted **glass console** (`RecommendationsConsole`) floating over the constellation, which has
    **receded into a defocused bokeh background** (`GlassBackground`: a static, blurred, drifting poster
    field + projector beams + scrim).
  - Flow: **reveal** (crystallize) → the same canvas **recedes** (~0.9s CSS blur-out, then the WebGL
    unmounts) → **glass** → opt-in **explore** (live map) with a back button. One `Constellation` instance
    kept mounted reveal→recede (keyed, no re-crystallize); blur masks the swap. `prefers-reduced-motion` →
    straight to glass.
  - Perf guardrail held: **no live WebGL behind `backdrop-filter`** — the steady-state background is cheap
    static `<img>` bokeh. Promoted `.glass`/`.bokeh`/`.glass-card` into `globals.css` + added
    `constellation-recede`. Deleted `RecommendationsTable.tsx` + the `/glass-proto` route.
  - Verified (Playwright): reveal → recede → glass → explore → back, plus a reduced-motion run — **zero page
    errors**. tsc + lint + `next build` clean.
- [x] **Phase 3.8 — explore map is a node-link constellation (dots), not a poster wall (user feedback)**
  - User: explore "still cluttered… hard to see the actual constellation." Added a `variant` prop to
    `Constellation`: **`posters`** (reveal, unchanged) vs **`dots`** (explore). Dots are **coloured by taste
    cluster** (`CLUSTER_COLORS`, muted 6-hue); recs are larger **amber-ringed, glowing stars**; **titles
    under the dots** (recs always, all on zoom-in, plus hovered); the **poster blooms on hover**;
    `pickingRadius={8}` makes small dots easy to hit. Edges + cluster labels turned back up.
  - Amends the §6.6 monochrome tenet (colour now encodes cluster in the explore map; amber still reserved
    for recs/"why"; shell stays monochrome).
  - Verified (Playwright): visible cluster structure, hover-poster bloom (Uncut Gems), zoom-in reveals all
    titles — zero page errors. tsc + lint + build clean.
  - **3.8a tuning (user feedback):** shrank dots (rec `0.36→0.18`, seed `0.24→0.14`) + tightened the amber
    rings (variant-aware `0.62→0.30`); brightened/thickened edges; moved cluster labels **on top** with a
    backing pill. **Real fix:** the graph was barely connected — **19 edges / 117 nodes**. `similarity_edges`
    cut kNN pairs at an absolute `threshold=0.15` (these sparse vectors are near-orthogonal). Added a
    **nearest-neighbour floor** + `threshold→0.08` → **260 edges, 0 isolated nodes**. Backend restart + cache
    rebuild; 44 tests pass; verified the connected web via Playwright.
- Next: Phase 4 — async job + SSE; stream the reveal during the *real* build (posters cascade in →
  crystallize → recede), bind the four-act animation to live phase events.

## Phase 3 retro (what I learned)
- The installed skills paid off here: `frontend-design` shaped the cinematic monochrome shell,
  `web-design-guidelines` audit caught quick a11y wins (aria-labels, img dims, real links),
  `fixing-motion-performance` thinking drove the w92 atlas. `webapp-testing`/Playwright gave real
  screenshot evidence (incl. confirming WebGL works headless with SwiftShader flags).
- deck.gl + Next 16 + React 19 work together; the one gotcha was the icon-atlas texture-size limit.

## Phase 3.7 retro (what I learned)
- Prototyping the look on a throwaway route (`/glass-proto`) before touching the real flow was the right
  call — the user could react to the actual feel, and promoting proven components was low-risk.
- The hard part was *legibility vs see-through*: glass over a busy poster field only works if the bokeh is
  defocused enough and the scrim is dark enough that text stays crisp. Tuned by screenshot, not by guessing.
- Keeping ONE `Constellation` mounted across reveal→recede (via a stable React `key`) avoids a
  re-crystallize flash; `emil-design-eng`'s "blur masks an imperfect transition" is exactly why the
  live-canvas → static-bokeh swap is invisible.
- Honoured the perf guardrail by construction: the steady-state background is static `<img>`s, so
  `backdrop-filter` never samples a live WebGL canvas.

## Phase 4 — SSE + pipeline intro
- [ ] Job endpoint + SSE; four-act animation; crystallization tween

## Phase 5 — Polish + deploy
- [ ] Mobile tuning, reduced-motion, error states, share links; deploy

## Open loops / blockers
- TMDB live validation blocked on `TMDB_API_KEY` being pasted into `.env` (intentional — secret).
