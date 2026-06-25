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


async def test_budget_resolves_only_top_and_bottom_slice() -> None:
    # 10 rated films (ratings 0.5..5.0). resolve_top=2 + resolve_bottom=2 → middle 6 skipped.
    movies = {
        f"film-{i}": {
            "slug": f"film-{i}",
            "name": f"F{i}",
            "year": 2000 + i,
            "rating": (i + 1) * 0.5,
            "liked": False,
        }
        for i in range(10)
    }

    class BigUser:
        def __init__(self, username: str) -> None:
            self.username = username

        def get_films(self) -> dict:
            return {"movies": movies, "rating_average": 2.75}

        def get_watchlist_movies(self) -> dict:
            return {}

    resolved: list[str] = []

    def tracking_movie(slug: str) -> FakeMovie:
        resolved.append(slug)
        return FakeMovie(slug)

    await scraper.scrape_user(
        "x",
        _redis(),
        user_factory=BigUser,
        movie_factory=tracking_movie,
        resolve_top=2,
        resolve_bottom=2,
    )
    # top-2 by rating = film-9 (5.0), film-8 (4.5); bottom-2 = film-0 (0.5), film-1 (1.0).
    assert set(resolved) == {"film-9", "film-8", "film-0", "film-1"}


async def test_small_profile_resolves_everything() -> None:
    res = await scraper.scrape_user(
        "x",
        _redis(),
        user_factory=FakeUser,
        movie_factory=FakeMovie,
        resolve_top=200,
        resolve_bottom=100,
    )
    # FakeUser has 1 rated film (film-a); budget covers all → it's resolved.
    assert next(f for f in res.films if f.slug == "film-a").tmdb_id == 100


async def test_empty_profile_raises() -> None:
    class EmptyUser:
        def __init__(self, username: str) -> None:
            self.username = username

        def get_films(self) -> dict:
            return {"movies": {}, "rating_average": None}

    with pytest.raises(scraper.EmptyProfileError):
        await scraper.scrape_user("x", _redis(), user_factory=EmptyUser, movie_factory=FakeMovie)
