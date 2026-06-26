"""Assemble the SPEC §5 graph payload (Phase 2).

Orchestrates the full pipeline — scrape → enrich → grow candidate pool → two-pass recommend
(OMDb-enriched) → UMAP project the displayed set (watched + recs) → cluster → similarity edges
→ assemble + cache. The result is the backend↔frontend contract the constellation renders.
"""

from __future__ import annotations

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


async def build_graph(
    username: str,
    redis: aioredis.Redis,
    http: httpx.AsyncClient,
    *,
    top_n: int = DEFAULT_TOP_N,
    refresh: bool = False,
) -> GraphPayload:
    """Build (or return cached) the full graph payload for a user."""
    cache_key = CACHE_KEY.format(username=username.lower())
    if not refresh:
        cached = await cache.get_json(redis, cache_key)
        if cached is not None:
            return GraphPayload.model_validate(cached)

    tmdb = create_tmdb_client(http, redis)
    scrape = await scraper.scrape_user(username, redis)
    rated = scrape.rated()
    if not rated:
        raise scraper.EmptyProfileError(username)
    user_mean = scrape.rating_average or sum(f.rating for f in rated) / len(rated)

    # Enrich watched films and carry over their rating/liked.
    watched_map = await tmdb.get_movies([f.tmdb_id for f in rated])
    watched: list[Film] = []
    for sf in rated:
        film = watched_map.get(sf.tmdb_id)
        if film is None:
            continue
        film.rating, film.liked = sf.rating, sf.liked
        watched.append(film)

    recs, rec_films = await _recommend(tmdb, http, redis, scrape, watched, user_mean, top_n)

    # Project + cluster + edge the displayed set (watched + recommendations).
    nodes_films = watched + rec_films
    matrix, _ = build_feature_matrix(nodes_films)
    coords = project_2d(matrix)
    labels = cluster_2d(coords)
    labelmap = cluster_labels(nodes_films, labels)
    edges = similarity_edges(matrix, nodes_films)

    score_by_id = {r.tmdb_id: r.score for r in recs}
    n_watched = len(watched)
    nodes = [
        Node(
            id=f"tmdb:{f.tmdb_id}",
            type="watched" if i < n_watched else "recommended",
            title=f.title,
            year=f.year,
            poster_url=f.poster_url,
            x=round(float(coords[i][0]), 4),
            y=round(float(coords[i][1]), 4),
            cluster=int(labels[i]),
            rating=f.rating if i < n_watched else None,
            score=None if i < n_watched else score_by_id.get(f.tmdb_id),
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
