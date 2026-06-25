"""Async TMDB v3 client.

One batched call per film via `append_to_response` hydrates genres, director, top cast,
keywords, decade, language, runtime, poster, and the recommendation/similar id lists.

We map Letterboxd → TMDB by the TMDB id taken off the Letterboxd film page, so this client
is keyed purely by `tmdb_id` — no fuzzy title matching (an architecture guardrail).
"""

from __future__ import annotations

from typing import Any

import httpx

from backend.config import Settings, get_settings
from backend.models import Film

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


def create_tmdb_client(http_client: httpx.AsyncClient) -> TMDBClient:
    """Build a TMDBClient from application settings."""
    return TMDBClient(http_client, get_settings())
