"""TMDBClient payload parsing — no network, via httpx.MockTransport."""

import httpx

from backend.config import Settings
from backend.tmdb import TMDBClient

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
