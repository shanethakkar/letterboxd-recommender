"""OMDb client — IMDb + Metacritic + Rotten Tomatoes ratings (SPEC §4.2).

OMDb's free tier is 1,000 requests/day, so callers enrich only the top contenders. Results
are cached **permanently** in Redis (`omdb:{imdb_id}`) since ratings change slowly. With no
API key (`create_omdb_client` returns None) or no `imdb_id`, enrichment is silently skipped
and the recommender falls back to TMDB-only quality.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterable
from typing import Any

import httpx
import redis.asyncio as aioredis

from backend.config import Settings, get_settings
from backend.models import Film

logger = logging.getLogger(__name__)

_CACHE_KEY = "omdb:{imdb_id}"


def parse_omdb(data: dict[str, Any]) -> dict[str, Any]:
    """Parse OMDb's stringly-typed payload into typed ratings (missing → None)."""
    out: dict[str, Any] = {
        "imdb_rating": None,
        "imdb_votes": None,
        "metascore": None,
        "rotten_tomatoes": None,
    }
    if data.get("Response") == "False":
        return out

    def _clean(value: str | None) -> str | None:
        return value if value and value != "N/A" else None

    if (r := _clean(data.get("imdbRating"))) is not None:
        try:
            out["imdb_rating"] = float(r)
        except ValueError:
            pass
    if (v := _clean(data.get("imdbVotes"))) is not None:
        try:
            out["imdb_votes"] = int(v.replace(",", ""))
        except ValueError:
            pass
    if (m := _clean(data.get("Metascore"))) is not None:
        try:
            out["metascore"] = int(m)
        except ValueError:
            pass
    for rating in data.get("Ratings", []):
        if rating.get("Source") == "Rotten Tomatoes":
            try:
                out["rotten_tomatoes"] = int(rating.get("Value", "").rstrip("%"))
            except ValueError:
                pass
    return out


class OMDBClient:
    """Async OMDb lookups by IMDb id, with a permanent Redis cache."""

    def __init__(
        self, http_client: httpx.AsyncClient, settings: Settings, redis: aioredis.Redis
    ) -> None:
        self._client = http_client
        self._settings = settings
        self._redis = redis

    async def enrich(self, films: Iterable[Film], *, concurrency: int = 8) -> None:
        """Attach IMDb/Metacritic/RT ratings to films that have an `imdb_id` (in place)."""
        targets = [f for f in films if f.imdb_id]
        sem = asyncio.Semaphore(concurrency)

        async def _one(film: Film) -> None:
            async with sem:
                ratings = await self._ratings_for(film.imdb_id)  # type: ignore[arg-type]
            if ratings:
                film.imdb_rating = ratings["imdb_rating"]
                film.imdb_votes = ratings["imdb_votes"]
                film.metascore = ratings["metascore"]
                film.rotten_tomatoes = ratings["rotten_tomatoes"]

        await asyncio.gather(*(_one(f) for f in targets))

    async def _ratings_for(self, imdb_id: str) -> dict[str, Any] | None:
        key = _CACHE_KEY.format(imdb_id=imdb_id)
        cached = await self._redis.get(key)
        if cached is not None:
            return json.loads(cached)
        data = await self._fetch(imdb_id)
        if data is None:
            return None  # transient failure — don't cache, allow retry
        ratings = parse_omdb(data)
        await self._redis.set(key, json.dumps(ratings))  # permanent
        return ratings

    async def _fetch(self, imdb_id: str) -> dict[str, Any] | None:
        try:
            resp = await self._client.get(
                self._settings.omdb_api_base,
                params={"apikey": self._settings.omdb_api_key, "i": imdb_id},
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            logger.warning("OMDb fetch failed for %s: %s", imdb_id, exc)
            return None


def create_omdb_client(http_client: httpx.AsyncClient, redis: aioredis.Redis) -> OMDBClient | None:
    """Build an OMDBClient, or None when no OMDb key is configured (enrichment skipped)."""
    settings = get_settings()
    if not settings.omdb_key_present:
        return None
    return OMDBClient(http_client, settings, redis)
