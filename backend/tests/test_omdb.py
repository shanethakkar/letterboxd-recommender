"""OMDb: payload parsing, enrichment, permanent cache, graceful skip."""

import json

import fakeredis.aioredis as fake_aioredis
import httpx

from backend.config import Settings
from backend.models import Film
from backend.omdb import OMDBClient, parse_omdb

SAMPLE = {
    "Response": "True",
    "imdbRating": "8.5",
    "imdbVotes": "1,234,567",
    "Metascore": "74",
    "Ratings": [
        {"Source": "Internet Movie Database", "Value": "8.5/10"},
        {"Source": "Rotten Tomatoes", "Value": "91%"},
        {"Source": "Metacritic", "Value": "74/100"},
    ],
}


def test_parse_omdb_typed_values() -> None:
    out = parse_omdb(SAMPLE)
    assert out["imdb_rating"] == 8.5
    assert out["imdb_votes"] == 1_234_567  # commas stripped
    assert out["metascore"] == 74
    assert out["rotten_tomatoes"] == 91  # from the Ratings[] array, % stripped


def test_parse_omdb_handles_na_and_missing() -> None:
    out = parse_omdb(
        {
            "Response": "True",
            "imdbRating": "N/A",
            "imdbVotes": "N/A",
            "Metascore": "N/A",
            "Ratings": [],
        }
    )
    assert out == {
        "imdb_rating": None,
        "imdb_votes": None,
        "metascore": None,
        "rotten_tomatoes": None,
    }


def test_parse_omdb_response_false() -> None:
    out = parse_omdb({"Response": "False", "Error": "Movie not found!"})
    assert all(v is None for v in out.values())


def test_settings_gate_omdb_key() -> None:
    assert Settings(omdb_api_key="").omdb_key_present is False
    assert Settings(omdb_api_key="x").omdb_key_present is True


def _client(handler, redis) -> OMDBClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OMDBClient(http, Settings(omdb_api_key="k"), redis)


def _redis():
    return fake_aioredis.FakeRedis(decode_responses=True)


async def test_enrich_sets_fields_caches_and_skips_films_without_imdb_id() -> None:
    fetched: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        fetched.append(request.url.params["i"])
        return httpx.Response(200, json=SAMPLE)

    redis = _redis()
    films = [
        Film(tmdb_id=1, title="A", imdb_id="tt0001"),
        Film(tmdb_id=2, title="B"),  # no imdb_id → skipped
    ]
    await _client(handler, redis).enrich(films)

    assert films[0].imdb_rating == 8.5
    assert films[0].metascore == 74
    assert films[0].rotten_tomatoes == 91
    assert films[1].imdb_rating is None
    assert fetched == ["tt0001"]  # only the film with an imdb_id was fetched
    assert await redis.get("omdb:tt0001") is not None
    assert await redis.ttl("omdb:tt0001") == -1  # permanent


async def test_enrich_reads_cache_without_refetching() -> None:
    redis = _redis()
    await redis.set(
        "omdb:tt0001",
        json.dumps({"imdb_rating": 7.0, "imdb_votes": 100, "metascore": 60, "rotten_tomatoes": 80}),
    )
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=SAMPLE)

    films = [Film(tmdb_id=1, title="A", imdb_id="tt0001")]
    await _client(handler, redis).enrich(films)

    assert films[0].imdb_rating == 7.0  # served from cache
    assert calls == []  # no network call
