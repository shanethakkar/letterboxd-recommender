"""Scraper: model mapping, permanent slug→tmdb_id cache, error translation.

All deterministic — letterboxdpy is replaced by injected fakes; Redis is fakeredis.
"""

import fakeredis.aioredis as fake_aioredis
import pytest

from backend import scraper


class FakeUser:
    """Stand-in for letterboxdpy.user.User."""

    def __init__(self, username: str) -> None:
        self.username = username

    def get_films(self) -> dict:
        return {
            "movies": {
                "film-a": {
                    "slug": "film-a",
                    "name": "Film A",
                    "year": 2010,
                    "rating": 4.5,
                    "liked": False,
                },
                "film-b": {
                    "slug": "film-b",
                    "name": "Film B",
                    "year": 2011,
                    "rating": None,
                    "liked": False,
                },
            },
            "rating_average": 4.5,
        }

    def get_watchlist_movies(self) -> dict:
        return {"1": {"slug": "film-w", "name": "W", "year": 2020}}


class FakeMovie:
    """Stand-in for letterboxdpy.movie.Movie — slug→tmdb_id map (string ids, like the real lib)."""

    _MAP = {"film-a": "100", "film-w": "300"}

    def __init__(self, slug: str) -> None:
        self.tmdb_id = self._MAP.get(slug)


def _redis():
    return fake_aioredis.FakeRedis(decode_responses=True)


async def test_maps_films_and_resolves_ids() -> None:
    res = await scraper.scrape_user("x", _redis(), user_factory=FakeUser, movie_factory=FakeMovie)
    film_a = next(f for f in res.films if f.slug == "film-a")
    assert film_a.tmdb_id == 100  # string "100" cast to int
    assert film_a.rating == 4.5
    # Unrated film-b is not resolved this phase (documented gap).
    assert next(f for f in res.films if f.slug == "film-b").tmdb_id is None
    assert [f.tmdb_id for f in res.rated()] == [100]
    assert res.watchlist_tmdb_ids == [300]
    assert res.logged_tmdb_ids() == {100, 300}


async def test_writes_permanent_cache() -> None:
    redis = _redis()
    await scraper.scrape_user("x", redis, user_factory=FakeUser, movie_factory=FakeMovie)
    assert await redis.get("lb:slug2tmdb:film-a") == "100"
    # TTL is None → permanent (the mapping never changes).
    assert await redis.ttl("lb:slug2tmdb:film-a") == -1


async def test_reads_cache_without_refetching() -> None:
    redis = _redis()
    await redis.set("lb:slug2tmdb:film-a", "999")
    calls: list[str] = []

    def counting_movie(slug: str) -> FakeMovie:
        calls.append(slug)
        return FakeMovie(slug)

    res = await scraper.scrape_user("x", redis, user_factory=FakeUser, movie_factory=counting_movie)
    assert next(f for f in res.films if f.slug == "film-a").tmdb_id == 999
    assert "film-a" not in calls  # served from cache, no Movie() call


class _ResourceNotFoundError(Exception):
    pass


class _PrivateRouteError(Exception):
    pass


@pytest.mark.parametrize(
    ("exc_type", "domain"),
    [
        (_ResourceNotFoundError, scraper.UserNotFoundError),
        (_PrivateRouteError, scraper.PrivateProfileError),
    ],
)
async def test_translates_letterboxd_errors(exc_type, domain) -> None:
    # _map_error keys off the exception class *name*, matching letterboxdpy's classes.
    exc_type.__name__ = exc_type.__name__.lstrip("_")

    def raising_user(_username: str):
        raise exc_type("boom")

    with pytest.raises(domain):
        await scraper.scrape_user("x", _redis(), user_factory=raising_user, movie_factory=FakeMovie)


async def test_empty_profile_raises() -> None:
    class EmptyUser:
        def __init__(self, username: str) -> None:
            self.username = username

        def get_films(self) -> dict:
            return {"movies": {}, "rating_average": None}

    with pytest.raises(scraper.EmptyProfileError):
        await scraper.scrape_user("x", _redis(), user_factory=EmptyUser, movie_factory=FakeMovie)
