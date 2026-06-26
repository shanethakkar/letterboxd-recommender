"""Assemble the SPEC §5 graph payload (Phase 2).

Orchestrates the full pipeline — scrape → enrich → grow candidate pool → two-pass recommend
(OMDb-enriched) → UMAP project the displayed set (watched + recs) → cluster → similarity edges
→ assemble + cache. The result is the backend↔frontend contract the constellation renders.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import httpx
import redis.asyncio as aioredis

from backend import cache, scraper
from backend.features import build_feature_matrix
from backend.models import Cluster, Film, GraphPayload, Node, Recommendation, Stats
from backend.omdb import create_omdb_client
from backend.projection import cluster_2d, cluster_labels, project_2d, similarity_edges
from backend.recommender import recommend
from backend.tmdb import create_tmdb_client

SEED_MIN_RATING = 4.0
SEED_MAX = 150
CONTENDERS = 120  # pass-1 shortlist OMDb-enriched before the final ranking
DEFAULT_TOP_N = 50  # recommendations shown in the constellation
CACHE_KEY = "rec:{username}"
CACHE_TTL = 60 * 60 * 24  # 24h (SPEC §4.6)

# An async progress sink for the streamed build (Phase 4). `None` = the plain synchronous path.
Emit = Callable[[dict], Awaitable[None]]


async def _emit(emit: Emit | None, event: dict) -> None:
    if emit is not None:
        await emit(event)


async def build_graph(
    username: str,
    redis: aioredis.Redis,
    http: httpx.AsyncClient,
    *,
    top_n: int = DEFAULT_TOP_N,
    refresh: bool = False,
    emit: Emit | None = None,
) -> GraphPayload:
    """Build (or return cached) the full graph payload for a user.

    When `emit` is given (Phase 4 streamed build), pushes `phase` + `nodes` (cascade) events as
    the pipeline runs. The caller emits the final `result`. With `emit=None` this is the original
    synchronous build, byte-for-byte.
    """
    cache_key = CACHE_KEY.format(username=username.lower())
    if not refresh:
        cached = await cache.get_json(redis, cache_key)
        if cached is not None:
            return GraphPayload.model_validate(cached)

    tmdb = create_tmdb_client(http, redis)
    await _emit(emit, {"event": "phase", "data": {"phase": "scraping"}})
    scrape = await scraper.scrape_user(username, redis)
    rated = scrape.rated()
    if not rated:
        raise scraper.EmptyProfileError(username)
    user_mean = scrape.rating_average or sum(f.rating for f in rated) / len(rated)
    total = len(rated)
    await _emit(
        emit,
        {
            "event": "phase",
            "data": {"phase": "scraping", "progress": 1.0, "detail": f"{total} films"},
        },
    )

    # Enrich watched films incrementally, carrying over rating/liked. Each batch streams out so the
    # frontend can cascade the posters in while scoring + embedding still run.
    await _emit(
        emit, {"event": "phase", "data": {"phase": "enriching", "detail": f"{total} films"}}
    )
    rating_by_id = {sf.tmdb_id: (sf.rating, sf.liked) for sf in rated}
    watched: list[Film] = []
    batch: list[dict] = []
    async for film in tmdb.stream_movies([f.tmdb_id for f in rated]):
        rl = rating_by_id.get(film.tmdb_id)
        if rl is None:
            continue
        film.rating, film.liked = rl
        watched.append(film)
        batch.append(
            {
                "id": f"tmdb:{film.tmdb_id}",
                "title": film.title,
                "year": film.year,
                "poster_url": film.poster_url,
                "rating": film.rating,
            }
        )
        if emit is not None and len(batch) >= 8:
            await _emit(
                emit,
                {
                    "event": "nodes",
                    "data": {"nodes": batch, "progress": round(len(watched) / total, 3)},
                },
            )
            batch = []
    if emit is not None and batch:
        await _emit(emit, {"event": "nodes", "data": {"nodes": batch, "progress": 1.0}})

    await _emit(emit, {"event": "phase", "data": {"phase": "scoring"}})
    recs, rec_films = await _recommend(tmdb, http, redis, scrape, watched, user_mean, top_n)

    # The map is recommendation-first: nodes = the recs + only the watched films that
    # *explain* them (their "because" seeds). The recommender still used all watched
    # internally; the displayed set is just recs + the films that earned them.
    rec_id_set = {f"tmdb:{f.tmdb_id}" for f in rec_films}
    seed_ids = {b.id for r in recs for b in r.because}
    seed_films = [
        f
        for f in watched
        if f"tmdb:{f.tmdb_id}" in seed_ids and f"tmdb:{f.tmdb_id}" not in rec_id_set
    ]
    nodes_films = rec_films + seed_films
    n_recs = len(rec_films)

    # Project + cluster + edge the displayed set. This block is CPU-bound (UMAP/sklearn) and would
    # block the event loop — run it off-thread so queued phase/nodes events actually flush.
    await _emit(emit, {"event": "phase", "data": {"phase": "embedding"}})

    def _embed() -> tuple:
        matrix, _ = build_feature_matrix(nodes_films)
        coords = project_2d(matrix)
        labels = cluster_2d(coords)
        labelmap = cluster_labels(nodes_films, labels)
        edges = similarity_edges(matrix, nodes_films)
        return coords, labels, labelmap, edges

    coords, labels, labelmap, edges = await asyncio.to_thread(_embed)

    score_by_id = {r.tmdb_id: r.score for r in recs}
    nodes = [
        Node(
            id=f"tmdb:{f.tmdb_id}",
            type="recommended" if i < n_recs else "watched",
            title=f.title,
            year=f.year,
            poster_url=f.poster_url,
            x=round(float(coords[i][0]), 4),
            y=round(float(coords[i][1]), 4),
            cluster=int(labels[i]),
            rating=None if i < n_recs else f.rating,
            score=score_by_id.get(f.tmdb_id) if i < n_recs else None,
            genres=f.genres,
            director=f.director,
        )
        for i, f in enumerate(nodes_films)
    ]

    clusters: list[Cluster] = []
    for cid in sorted({int(c) for c in labels}):
        if cid == -1:  # HDBSCAN noise
            continue
        members = coords[labels == cid]
        clusters.append(
            Cluster(
                id=cid,
                label=labelmap.get(cid),
                centroid=[
                    round(float(members[:, 0].mean()), 4),
                    round(float(members[:, 1].mean()), 4),
                ],
            )
        )

    payload = GraphPayload(
        username=getattr(scrape, "username", username),
        generated_at=datetime.now(UTC).isoformat(),
        stats=Stats(rated=len(rated), avg_rating=round(user_mean, 2), clusters=len(clusters)),
        nodes=nodes,
        edges=edges,
        recommendations=recs,
        clusters=clusters,
    )
    await cache.set_json(redis, cache_key, payload.model_dump(mode="json"), ttl_seconds=CACHE_TTL)
    return payload


async def _recommend(
    tmdb,
    http: httpx.AsyncClient,
    redis: aioredis.Redis,
    scrape: scraper.ScrapeResult,
    watched: list[Film],
    user_mean: float,
    top_n: int,
) -> tuple[list[Recommendation], list[Film]]:
    """Two-pass recommend (OMDb-enrich the shortlist) → (recs, the recommended Films)."""
    seeds = sorted(watched, key=lambda f: f.rating or 0.0, reverse=True)
    top_seeds = [f for f in seeds if (f.rating or 0) >= SEED_MIN_RATING][:SEED_MAX] or seeds[
        :SEED_MAX
    ]
    candidates, provenance = await tmdb.grow_candidate_pool(top_seeds, scrape.logged_tmdb_ids())

    cand_by_id = {f.tmdb_id: f for f in candidates}
    prov_by_id = dict(zip([f.tmdb_id for f in candidates], provenance, strict=True))

    pass1 = recommend(
        watched, candidates, provenance, user_mean=user_mean, top_n=CONTENDERS, mmr_lambda=1.0
    )
    contenders = [cand_by_id[r.tmdb_id] for r in pass1]
    contender_prov = [prov_by_id[r.tmdb_id] for r in pass1]

    omdb = create_omdb_client(http, redis)
    if omdb is not None:
        await omdb.enrich(contenders)

    recs = recommend(watched, contenders, contender_prov, user_mean=user_mean, top_n=top_n)
    by_id = {f.tmdb_id: f for f in contenders}
    return recs, [by_id[r.tmdb_id] for r in recs]
