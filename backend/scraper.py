"""Letterboxd scraper (SPEC §4.1).

`letterboxdpy` is synchronous (curl_cffi) and does NOT return TMDB ids in its bulk film
list — each film's TMDB id must be read off its film page via `Movie(slug).tmdb_id`
(one request per film; still the Letterboxd-page id, no fuzzy matching — guardrail intact).
See DECISIONS.md (2026-06-25, "TMDB id requires a per-film Letterboxd fetch").

We therefore: run the sync calls in threads (`asyncio.to_thread`), bound concurrency with a
semaphore + jitter to stay polite, and **cache `slug→tmdb_id` permanently in Redis** (the
mapping never changes), so re-scrapes and films shared across users are nearly free.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable
from typing import Any

import redis.asyncio as aioredis

from backend.models import ScrapedFilm, ScrapeResult

logger = logging.getLogger(__name__)

_SLUG2TMDB_KEY = "lb:slug2tmdb:{slug}"
_MISSING = ""  # cache sentinel: film has no resolvable TMDB id (avoid re-fetching)


class ScrapeError(Exception):
    """Base class for scrape failures the frontend can render as direction (SPEC §6.1)."""


class UserNotFoundError(ScrapeError):
    """No such public Letterboxd profile."""


class PrivateProfileError(ScrapeError):
    """Profile exists but is private — only public diaries can be mapped."""


class AccessBlockedError(ScrapeError):
    """Letterboxd blocked the request (e.g. IP/VPN)."""


class EmptyProfileError(ScrapeError):
    """Profile is public but has logged no films."""


def _map_error(exc: Exception) -> ScrapeError | None:
    """Translate a letterboxdpy exception into a domain error (by class name, so we
    don't hard-depend on the library's internal exception module)."""
    name = type(exc).__name__
    if name == "ResourceNotFoundError":
        return UserNotFoundError(name)
    if name == "PrivateRouteError":
        return PrivateProfileError(name)
    if name == "AccessDeniedError":
        return AccessBlockedError(name)
    return None


def _default_factories() -> tuple[Callable[[str], Any], Callable[[str], Any]]:
    """Import letterboxdpy lazily so the package isn't required to import this module
    (and so tests can inject fakes instead)."""
    from letterboxdpy.movie import Movie
    from letterboxdpy.user import User

    return User, Movie


async def scrape_user(
    username: str,
    redis: aioredis.Redis,
    *,
    user_factory: Callable[[str], Any] | None = None,
    movie_factory: Callable[[str], Any] | None = None,
    resolve_concurrency: int = 4,
) -> ScrapeResult:
    """Scrape a public Letterboxd profile into a `ScrapeResult`.

    Resolves TMDB ids only for films that carry taste signal (rated or liked) plus the
    watchlist (for exclusion); unrated-watched films are left with `tmdb_id=None` (a small,
    documented exclusion gap, cheap to close later since results are cached).
    """
    if user_factory is None or movie_factory is None:
        default_user, default_movie = _default_factories()
        user_factory = user_factory or default_user
        movie_factory = movie_factory or default_movie

    # 1. Construct the user (maps 404 / private / blocked to domain errors).
    try:
        user = await asyncio.to_thread(user_factory, username)
        films_data = await asyncio.to_thread(user.get_films)
    except Exception as exc:  # noqa: BLE001 — re-raised as a typed domain error below
        mapped = _map_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise ScrapeError(str(exc)) from exc

    movies: dict[str, dict[str, Any]] = films_data.get("movies", {})
    if not movies:
        raise EmptyProfileError(username)

    films = [
        ScrapedFilm(
            slug=v["slug"],
            title=v.get("name", v["slug"]),
            year=v.get("year"),
            rating=v.get("rating"),
            liked=bool(v.get("liked", False)),
        )
        for v in movies.values()
    ]

    # 2. Watchlist (for exclusion). Non-critical — tolerate failure.
    watchlist_slugs: list[str] = []
    try:
        watchlist = await asyncio.to_thread(user.get_watchlist_movies)
        watchlist_slugs = [v["slug"] for v in watchlist.values() if "slug" in v]
    except Exception as exc:  # noqa: BLE001
        logger.warning("watchlist fetch failed for %s: %s", username, exc)

    # 3. Resolve slug -> tmdb_id (cached, bounded concurrency) for taste + watchlist films.
    sem = asyncio.Semaphore(resolve_concurrency)
    taste_films = [f for f in films if f.rating is not None or f.liked]
    to_resolve = {f.slug for f in taste_films} | set(watchlist_slugs)
    resolved = await _resolve_slugs(to_resolve, redis, movie_factory, sem)

    for f in films:
        f.tmdb_id = resolved.get(f.slug)
    watchlist_tmdb_ids = sorted(
        {resolved[s] for s in watchlist_slugs if resolved.get(s) is not None}
    )

    return ScrapeResult(
        username=getattr(user, "username", username),
        films=films,
        watchlist_tmdb_ids=watchlist_tmdb_ids,
        rating_average=films_data.get("rating_average"),
    )


async def _resolve_slugs(
    slugs: set[str],
    redis: aioredis.Redis,
    movie_factory: Callable[[str], Any],
    sem: asyncio.Semaphore,
) -> dict[str, int | None]:
    """Resolve many slugs to TMDB ids concurrently, reading/writing the permanent cache."""
    pairs = await asyncio.gather(
        *(_resolve_slug(slug, redis, movie_factory, sem) for slug in slugs)
    )
    return dict(pairs)


async def _resolve_slug(
    slug: str,
    redis: aioredis.Redis,
    movie_factory: Callable[[str], Any],
    sem: asyncio.Semaphore,
) -> tuple[str, int | None]:
    """Return (slug, tmdb_id|None), using the permanent Redis cache when present."""
    key = _SLUG2TMDB_KEY.format(slug=slug)
    cached = await redis.get(key)
    if cached is not None:
        return slug, (int(cached) if cached != _MISSING else None)

    async with sem:
        await asyncio.sleep(random.uniform(0.05, 0.25))  # jitter — be polite
        try:
            movie = await asyncio.to_thread(movie_factory, slug)
            raw = getattr(movie, "tmdb_id", None)
            tmdb_id = int(raw) if raw else None
        except Exception as exc:  # noqa: BLE001 — one bad film shouldn't sink the scrape
            logger.warning("tmdb_id resolution failed for %s: %s", slug, exc)
            return slug, None

    # Cache permanently (no TTL). Empty string marks a known-missing id.
    await redis.set(key, str(tmdb_id) if tmdb_id is not None else _MISSING)
    return slug, tmdb_id
