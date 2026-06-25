"""Async TMDB v3 client.

One batched call per film via `append_to_response` hydrates genres, director, top cast,
keywords, decade, language, runtime, poster, and the recommendation/similar id lists.

We map Letterboxd → TMDB by the TMDB id taken off the Letterboxd film page, so this client
is keyed purely by `tmdb_id` — no fuzzy title matching (an architecture guardrail).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from typing import Any

import httpx

from backend.config import Settings, get_settings
from backend.models import Film

logger = logging.getLogger(__name__)

_APPEND = "credits,keywords,recommendations,similar"
_TOP_CAST = 5


class TMDBClient:
    """Thin async wrapper over the TMDB movie endpoint.

    The `httpx.AsyncClient` is injected so the FastAPI app can own its lifecycle and
    tests can supply a `MockTransport` (no network).
    """

    def __init__(self, http_client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = http_client
        self._settings = settings

    async def get_movie(self, tmdb_id: int) -> Film:
        """Fetch and parse one film by its TMDB id."""
        resp = await self._client.get(
            f"{self._settings.tmdb_api_base}/movie/{tmdb_id}",
            params={
                "api_key": self._settings.tmdb_api_key,
                "append_to_response": _APPEND,
            },
        )
        resp.raise_for_status()
        return self._parse(resp.json())

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

    async def discover_backfill(self, *, pages: int = 2, min_votes: int = 2000) -> list[int]:
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


def create_tmdb_client(http_client: httpx.AsyncClient) -> TMDBClient:
    """Build a TMDBClient from application settings."""
    return TMDBClient(http_client, get_settings())
