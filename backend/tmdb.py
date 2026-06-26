"""Async TMDB v3 client.

One batched call per film via `append_to_response` hydrates genres, director, top cast,
keywords, decade, language, runtime, poster, and the recommendation/similar id lists.

We map Letterboxd → TMDB by the TMDB id taken off the Letterboxd film page, so this client
is keyed purely by `tmdb_id` — no fuzzy title matching (an architecture guardrail).
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import AsyncIterator, Iterable
from typing import Any

import httpx
import redis.asyncio as aioredis

from backend.config import Settings, get_settings
from backend.models import Film

logger = logging.getLogger(__name__)

_APPEND = "credits,keywords,recommendations,similar"
_TOP_CAST = 5
_MOVIE_CACHE_KEY = "tmdb:movie:{tmdb_id}"
_MOVIE_TTL = 60 * 60 * 24 * 30  # 30 days — TMDB metadata drifts slowly

# TMDB's fixed movie-genre ids (static; used to query /discover by the user's top genres).
_GENRE_NAME_TO_ID: dict[str, int] = {
    "Action": 28,
    "Adventure": 12,
    "Animation": 16,
    "Comedy": 35,
    "Crime": 80,
    "Documentary": 99,
    "Drama": 18,
    "Family": 10751,
    "Fantasy": 14,
    "History": 36,
    "Horror": 27,
    "Music": 10402,
    "Mystery": 9648,
    "Romance": 10749,
    "Science Fiction": 878,
    "TV Movie": 10770,
    "Thriller": 53,
    "War": 10752,
    "Western": 37,
}


def _top_genre_ids(seed_films: Iterable[Film], n: int = 3) -> list[int]:
    """The user's most common genres (among seeds) → TMDB genre ids for /discover."""
    counts = Counter(g for f in seed_films for g in f.genres)
    ids = [_GENRE_NAME_TO_ID[name] for name, _ in counts.most_common() if name in _GENRE_NAME_TO_ID]
    return ids[:n]


class TMDBClient:
    """Thin async wrapper over the TMDB movie endpoint.

    The `httpx.AsyncClient` is injected so the FastAPI app can own its lifecycle and
    tests can supply a `MockTransport` (no network).
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        settings: Settings,
        redis: aioredis.Redis | None = None,
    ) -> None:
        self._client = http_client
        self._settings = settings
        self._redis = redis

    async def get_movie(self, tmdb_id: int) -> Film:
        """Fetch and parse one film by its TMDB id (Redis-cached when available)."""
        key = _MOVIE_CACHE_KEY.format(tmdb_id=tmdb_id)
        if self._redis is not None:
            cached = await self._redis.get(key)
            if cached is not None:
                return Film.model_validate_json(cached)

        resp = await self._client.get(
            f"{self._settings.tmdb_api_base}/movie/{tmdb_id}",
            params={
                "api_key": self._settings.tmdb_api_key,
                "append_to_response": _APPEND,
            },
        )
        resp.raise_for_status()
        film = self._parse(resp.json())

        if self._redis is not None:
            await self._redis.set(key, film.model_dump_json(), ex=_MOVIE_TTL)
        return film

    async def get_movies(self, ids: Iterable[int], *, concurrency: int = 8) -> dict[int, Film]:
        """Fetch many films concurrently (bounded). Failures are logged and skipped."""
        sem = asyncio.Semaphore(concurrency)
        unique_ids = list(dict.fromkeys(ids))  # de-dupe, preserve order

        async def _one(tmdb_id: int) -> tuple[int, Film] | None:
            async with sem:
                try:
                    return tmdb_id, await self.get_movie(tmdb_id)
                except httpx.HTTPError as exc:
                    logger.warning("TMDB fetch failed for %s: %s", tmdb_id, exc)
                    return None

        results = await asyncio.gather(*(_one(i) for i in unique_ids))
        return {tmdb_id: film for r in results if r is not None for tmdb_id, film in [r]}

    async def stream_movies(
        self, ids: Iterable[int], *, concurrency: int = 8
    ) -> AsyncIterator[Film]:
        """Yield films as each resolves (Phase 4 cascade) — same bounded fetch as `get_movies`,
        but films surface in completion order instead of all at once. Failures are skipped."""
        sem = asyncio.Semaphore(concurrency)
        unique_ids = list(dict.fromkeys(ids))

        async def _one(tmdb_id: int) -> Film | None:
            async with sem:
                try:
                    return await self.get_movie(tmdb_id)
                except httpx.HTTPError as exc:
                    logger.warning("TMDB fetch failed for %s: %s", tmdb_id, exc)
                    return None

        tasks = [asyncio.create_task(_one(i)) for i in unique_ids]
        for fut in asyncio.as_completed(tasks):
            film = await fut
            if film is not None:
                yield film

    async def discover_backfill(self, *, pages: int = 4, min_votes: int = 2000) -> list[int]:
        """Acclaimed/popular backfill ids from `/discover/movie` (SPEC §4.2).

        Sorted by vote count with a vote floor, so the pool never starves on users
        whose seeds have few TMDB recommendations.
        """
        ids: list[int] = []
        for page in range(1, pages + 1):
            try:
                resp = await self._client.get(
                    f"{self._settings.tmdb_api_base}/discover/movie",
                    params={
                        "api_key": self._settings.tmdb_api_key,
                        "sort_by": "vote_count.desc",
                        "vote_count.gte": min_votes,
                        "page": page,
                    },
                )
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning("TMDB discover backfill failed (page %s): %s", page, exc)
                break
            ids.extend(r["id"] for r in resp.json().get("results", []) if "id" in r)
        return ids

    async def discover_by_genres(
        self, genre_ids: list[int], *, pages: int = 5, min_votes: int = 500
    ) -> list[int]:
        """Taste-filtered discover: well-voted films in the user's top genres (SPEC §4.2).

        An attribute-based candidate source that reaches on-taste films the rec-graph misses.
        Genres OR-combined; the vote floor keeps results recognizable; scoring adds precision.
        """
        if not genre_ids:
            return []
        ids: list[int] = []
        for page in range(1, pages + 1):
            try:
                resp = await self._client.get(
                    f"{self._settings.tmdb_api_base}/discover/movie",
                    params={
                        "api_key": self._settings.tmdb_api_key,
                        "with_genres": "|".join(str(g) for g in genre_ids),
                        "sort_by": "vote_count.desc",
                        "vote_count.gte": min_votes,
                        "page": page,
                    },
                )
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning("TMDB genre discover failed (page %s): %s", page, exc)
                break
            ids.extend(r["id"] for r in resp.json().get("results", []) if "id" in r)
        return ids

    async def grow_candidate_pool(
        self,
        seed_films: list[Film],
        exclude_ids: set[int],
        *,
        backfill_pages: int = 4,
        taste_pages: int = 5,
        expand_top: int = 200,
        max_candidates: int = 3000,
        memo: dict[int, Film] | None = None,
    ) -> tuple[list[Film], list[float]]:
        """Build + enrich the candidate pool from three sources, for recall (SPEC §4.2).

        (1) the rec-graph: seeds' TMDB recommendations/similar; (2) **taste-filtered discover**:
        well-voted films in the user's top genres (reaches on-taste films the graph misses);
        (3) a generic acclaimed/popular backfill. If there's room under `max_candidates`, a 2nd
        hop adds neighbours of the strongest hop-1 candidates. Returns enriched candidate Films
        + aligned provenance (graph hits count; taste-discover enters at 1.0, 2-hop at 0.5).
        `memo` lets callers share enrichment across calls (e.g. eval splits).
        """
        cache = memo if memo is not None else {}

        async def _enrich(ids: list[int]) -> None:
            missing = [i for i in ids if i not in cache]
            if missing:
                cache.update(await self.get_movies(missing))

        backfill = await self.discover_backfill(pages=backfill_pages)
        taste_ids = await self.discover_by_genres(_top_genre_ids(seed_films), pages=taste_pages)
        provenance: dict[int, float] = {
            cid: float(n)
            for cid, n in build_candidate_pool(seed_films, exclude_ids, backfill).items()
        }
        for tid in taste_ids:  # attribute-matched → enter at a single-graph-hit weight
            if tid not in exclude_ids:
                provenance[tid] = max(provenance.get(tid, 0.0), 1.0)

        def _ranked() -> list[int]:
            return [c for c, _ in sorted(provenance.items(), key=lambda kv: kv[1], reverse=True)]

        # Hop 1.
        await _enrich(_ranked()[:max_candidates])
        enriched_ids = [c for c in _ranked() if c in cache][:max_candidates]

        # Hop 2 — only if there's headroom under the cap.
        if len(enriched_ids) < max_candidates:
            for cid in enriched_ids[:expand_top]:
                f = cache[cid]
                for nid in (*f.tmdb_recommendations, *f.tmdb_similar):
                    if nid not in exclude_ids:
                        provenance[nid] = provenance.get(nid, 0.0) + 0.5
            hop2 = [c for c in _ranked() if c not in cache][: max_candidates - len(enriched_ids)]
            await _enrich(hop2)

        ranked = sorted(
            ((c, provenance[c]) for c in provenance if c in cache and c not in exclude_ids),
            key=lambda kv: kv[1],
            reverse=True,
        )[:max_candidates]
        return [cache[c] for c, _ in ranked], [p for _, p in ranked]

    def _parse(self, data: dict[str, Any]) -> Film:
        release_date = data.get("release_date") or ""
        year = int(release_date[:4]) if release_date[:4].isdigit() else None

        credits = data.get("credits") or {}
        director = next(
            (c["name"] for c in credits.get("crew", []) if c.get("job") == "Director"),
            None,
        )
        cast = sorted(credits.get("cast", []), key=lambda c: c.get("order", 1_000_000))
        top_cast = [c["name"] for c in cast[:_TOP_CAST] if c.get("name")]

        keywords = [
            k["name"] for k in (data.get("keywords") or {}).get("keywords", []) if k.get("name")
        ]

        return Film(
            tmdb_id=data["id"],
            title=data.get("title") or data.get("original_title") or "",
            year=year,
            genres=[g["name"] for g in data.get("genres", []) if g.get("name")],
            director=director,
            top_cast=top_cast,
            keywords=keywords,
            release_decade=(year // 10 * 10) if year else None,
            original_language=data.get("original_language"),
            runtime=data.get("runtime"),
            poster_url=self._poster_url(data.get("poster_path")),
            tmdb_recommendations=self._result_ids(data.get("recommendations")),
            tmdb_similar=self._result_ids(data.get("similar")),
            popularity=data.get("popularity"),
            vote_average=data.get("vote_average"),
            vote_count=data.get("vote_count"),
            imdb_id=data.get("imdb_id"),  # top-level on /movie/{id} — free, no extra call
        )

    def _poster_url(self, poster_path: str | None) -> str | None:
        if not poster_path:
            return None
        base = self._settings.tmdb_image_base
        size = self._settings.poster_size
        return f"{base}/{size}{poster_path}"

    @staticmethod
    def _result_ids(block: dict[str, Any] | None) -> list[int]:
        return [r["id"] for r in (block or {}).get("results", []) if "id" in r]


def build_candidate_pool(
    seed_films: Iterable[Film],
    exclude_ids: set[int],
    backfill_ids: Iterable[int] = (),
) -> dict[int, int]:
    """Build the candidate pool with a rec-graph provenance count per candidate.

    A candidate's provenance count = how many seed films surfaced it via TMDB
    `recommendations`/`similar`. That count is the hybrid/collaborative signal used in
    scoring (SPEC §4.4). Backfill ids enter at provenance 0 so the pool never starves.
    Anything already logged by the user (``exclude_ids``) is removed.
    """
    provenance: dict[int, int] = {}
    for film in seed_films:
        for cid in (*film.tmdb_recommendations, *film.tmdb_similar):
            provenance[cid] = provenance.get(cid, 0) + 1
    for cid in backfill_ids:
        provenance.setdefault(cid, 0)
    for cid in exclude_ids:
        provenance.pop(cid, None)
    return provenance


def create_tmdb_client(
    http_client: httpx.AsyncClient, redis: aioredis.Redis | None = None
) -> TMDBClient:
    """Build a TMDBClient from application settings (Redis enables response caching)."""
    return TMDBClient(http_client, get_settings(), redis=redis)
