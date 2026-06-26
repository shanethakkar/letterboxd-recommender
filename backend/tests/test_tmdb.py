"""TMDBClient payload parsing — no network, via httpx.MockTransport."""

import fakeredis.aioredis as fake_aioredis
import httpx

from backend.config import Settings
from backend.models import Film
from backend.tmdb import TMDBClient, _top_genre_ids

# Trimmed but structurally faithful TMDB `append_to_response` payload for Inception.
SAMPLE = {
    "id": 27205,
    "title": "Inception",
    "original_title": "Inception",
    "release_date": "2010-07-15",
    "original_language": "en",
    "runtime": 148,
    "poster_path": "/oYuLEt3zVCKq57qu2F8dT7NIa6f.jpg",
    "genres": [{"id": 28, "name": "Action"}, {"id": 878, "name": "Science Fiction"}],
    "credits": {
        "cast": [
            {"name": "Leonardo DiCaprio", "order": 0},
            {"name": "Joseph Gordon-Levitt", "order": 1},
            {"name": "Elliot Page", "order": 2},
            {"name": "Tom Hardy", "order": 3},
            {"name": "Ken Watanabe", "order": 4},
            {"name": "Cillian Murphy", "order": 5},
        ],
        "crew": [
            {"name": "Christopher Nolan", "job": "Director"},
            {"name": "Hans Zimmer", "job": "Original Music Composer"},
        ],
    },
    "keywords": {"keywords": [{"id": 1, "name": "dream"}, {"id": 2, "name": "heist"}]},
    "recommendations": {"results": [{"id": 155}, {"id": 49026}]},
    "similar": {"results": [{"id": 1124}, {"id": 11324}]},
}


def _client_returning(payload: dict) -> TMDBClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/3/movie/27205"
        assert request.url.params["append_to_response"] == (
            "credits,keywords,recommendations,similar"
        )
        return httpx.Response(200, json=payload)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return TMDBClient(http, Settings(tmdb_api_key="test-key"))


async def test_parses_core_fields() -> None:
    film = await _client_returning(SAMPLE).get_movie(27205)

    assert film.tmdb_id == 27205
    assert film.title == "Inception"
    assert film.year == 2010
    assert film.release_decade == 2010
    assert film.runtime == 148
    assert film.original_language == "en"
    assert film.genres == ["Action", "Science Fiction"]


async def test_parses_credits_keywords_and_related_ids() -> None:
    film = await _client_returning(SAMPLE).get_movie(27205)

    assert film.director == "Christopher Nolan"  # picked from crew by job
    assert film.top_cast == [  # capped at 5, ordered by `order`
        "Leonardo DiCaprio",
        "Joseph Gordon-Levitt",
        "Elliot Page",
        "Tom Hardy",
        "Ken Watanabe",
    ]
    assert film.keywords == ["dream", "heist"]
    assert film.tmdb_recommendations == [155, 49026]
    assert film.tmdb_similar == [1124, 11324]


async def test_builds_poster_url_from_image_base() -> None:
    film = await _client_returning(SAMPLE).get_movie(27205)
    assert film.poster_url == ("https://image.tmdb.org/t/p/w185/oYuLEt3zVCKq57qu2F8dT7NIa6f.jpg")


async def test_grow_candidate_pool_reaches_two_hops() -> None:
    # seed → recommends 1 & 2 (hop 1); film 1 → recommends 99 (hop 2, no seed points to it).
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/3/discover/movie":
            return httpx.Response(200, json={"results": []})
        mid = int(request.url.path.rsplit("/", 1)[1])
        recs = {1: [99]}.get(mid, [])
        return httpx.Response(
            200,
            json={
                "id": mid,
                "title": str(mid),
                "vote_count": 1000,
                "recommendations": {"results": [{"id": r} for r in recs]},
                "similar": {"results": []},
            },
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = TMDBClient(http, Settings(tmdb_api_key="k"))
    seed = Film(tmdb_id=10, title="seed", tmdb_recommendations=[1, 2])

    films, prov = await client.grow_candidate_pool([seed], set(), expand_top=10, max_candidates=50)
    ids = {f.tmdb_id for f in films}
    assert {1, 2} <= ids  # hop 1: direct seed recommendations
    assert 99 in ids  # hop 2: reachable only via film 1's recommendations
    assert len(prov) == len(films)


def test_top_genre_ids_maps_names_to_ids() -> None:
    films = [
        Film(tmdb_id=1, title="a", genres=["Crime", "Drama"]),
        Film(tmdb_id=2, title="b", genres=["Crime"]),
    ]
    ids = _top_genre_ids(films, n=2)
    assert ids[0] == 80  # Crime (most common) → TMDB id 80
    assert set(ids) == {80, 18}  # + Drama (18)


async def test_grow_candidate_pool_includes_taste_discover() -> None:
    # The seed's genre drives a /discover query that returns film 500 (not in the rec graph).
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/3/discover/movie":
            if "with_genres" in request.url.params:
                return httpx.Response(200, json={"results": [{"id": 500}]})
            return httpx.Response(200, json={"results": []})  # generic backfill
        mid = int(request.url.path.rsplit("/", 1)[1])
        return httpx.Response(
            200,
            json={
                "id": mid,
                "title": str(mid),
                "vote_count": 1000,
                "recommendations": {"results": []},
                "similar": {"results": []},
            },
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = TMDBClient(http, Settings(tmdb_api_key="k"))
    seed = Film(tmdb_id=10, title="seed", genres=["Crime"], tmdb_recommendations=[1])

    films, _ = await client.grow_candidate_pool([seed], set(), max_candidates=50)
    ids = {f.tmdb_id for f in films}
    assert 1 in ids  # rec-graph source
    assert 500 in ids  # taste-filtered discover source


async def test_get_movie_caches_in_redis() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=SAMPLE)

    redis = fake_aioredis.FakeRedis(decode_responses=True)
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = TMDBClient(http, Settings(tmdb_api_key="k"), redis=redis)

    first = await client.get_movie(27205)
    second = await client.get_movie(27205)
    assert first.title == second.title == "Inception"
    assert len(calls) == 1  # second call served from the Redis cache
