"""build_graph end-to-end on a synthetic profile (scraper + TMDB faked, no network)."""

import fakeredis.aioredis as fake_aioredis
import httpx

import backend.graph as gph
import backend.jobs as jobs
from backend.models import Film, ScrapedFilm, ScrapeResult

WATCHED = list(range(1, 16))  # 15 watched, tmdb ids 1..15


def _film(i: int, genre: str = "Action") -> Film:
    return Film(
        tmdb_id=i,
        title=f"F{i}",
        genres=[genre],
        director=f"D{i % 3}",
        vote_count=1000,
        vote_average=7.0,
        year=2015,
    )


class _FakeTMDB:
    async def stream_movies(self, ids, **_kw):
        for i in ids:
            yield _film(i)

    async def grow_candidate_pool(self, seed_films, exclude_ids, **_kw):
        # Share the genre with watched so recs get "because" explanations (→ seed nodes).
        films = [_film(100 + i) for i in range(20)]  # 20 unseen candidates
        return films, [1.0] * len(films)


async def test_build_graph_matches_spec5_shape(monkeypatch) -> None:
    rated = [ScrapedFilm(slug=f"f{i}", tmdb_id=i, title=f"F{i}", rating=4.5) for i in WATCHED]
    scrape_result = ScrapeResult(
        username="x", films=rated, watchlist_tmdb_ids=[], rating_average=4.0
    )

    async def fake_scrape(username, redis, **_kw):
        return scrape_result

    monkeypatch.setattr(gph.scraper, "scrape_user", fake_scrape)
    monkeypatch.setattr(gph, "create_tmdb_client", lambda http, redis=None: _FakeTMDB())
    monkeypatch.setattr(gph, "create_omdb_client", lambda http, redis: None)

    redis = fake_aioredis.FakeRedis(decode_responses=True)
    async with httpx.AsyncClient() as http:
        payload = await gph.build_graph("x", redis, http, top_n=10, refresh=True)

    assert payload.username == "x"
    assert payload.stats.rated == 15

    watched_nodes = [n for n in payload.nodes if n.type == "watched"]
    rec_nodes = [n for n in payload.nodes if n.type == "recommended"]
    seed_ids = {b.id for r in payload.recommendations for b in r.because}
    assert len(rec_nodes) > 0
    assert watched_nodes  # the "because" seed films appear in the map…
    assert {n.id for n in watched_nodes} <= seed_ids  # …and ONLY those (recs-first map)
    assert all(n.id.startswith("tmdb:") for n in payload.nodes)
    assert all(n.rating is not None for n in watched_nodes)  # seeds carry rating
    assert all(n.score is not None for n in rec_nodes)  # recs carry score

    node_ids = {n.id for n in payload.nodes}
    for e in payload.edges:  # edge endpoints exist among nodes
        assert e.source in node_ids
        assert e.target in node_ids

    # 2nd build (no refresh) is served from cache → identical timestamp.
    async with httpx.AsyncClient() as http:
        again = await gph.build_graph("x", redis, http)
    assert again.generated_at == payload.generated_at


def _patch_pipeline(monkeypatch, scrape_result) -> None:
    async def fake_scrape(username, redis, **_kw):
        return scrape_result

    monkeypatch.setattr(gph.scraper, "scrape_user", fake_scrape)
    monkeypatch.setattr(gph, "create_tmdb_client", lambda http, redis=None: _FakeTMDB())
    monkeypatch.setattr(gph, "create_omdb_client", lambda http, redis: None)


async def test_stream_build_emits_phases_nodes_then_result(monkeypatch) -> None:
    rated = [ScrapedFilm(slug=f"f{i}", tmdb_id=i, title=f"F{i}", rating=4.5) for i in WATCHED]
    _patch_pipeline(
        monkeypatch,
        ScrapeResult(username="x", films=rated, watchlist_tmdb_ids=[], rating_average=4.0),
    )

    redis = fake_aioredis.FakeRedis(decode_responses=True)
    async with httpx.AsyncClient() as http:
        events = [e async for e in jobs.stream_build("x", redis, http, refresh=True)]

    phases = [e["data"]["phase"] for e in events if e["event"] == "phase"]
    assert phases[0] == "scraping"
    for expected in ("enriching", "scoring", "embedding"):
        assert expected in phases
    # the poster cascade: ≥1 nodes batch, each entry has a tmdb id + the fields the cloud needs
    node_batches = [e for e in events if e["event"] == "nodes"]
    assert node_batches
    for ev in node_batches:
        for n in ev["data"]["nodes"]:
            assert n["id"].startswith("tmdb:") and "poster_url" in n and "rating" in n
    # ends with the full payload
    assert events[-1]["event"] == "result"
    assert events[-1]["data"]["stats"]["rated"] == 15


async def test_stream_build_emits_error_for_empty_profile(monkeypatch) -> None:
    _patch_pipeline(
        monkeypatch,
        ScrapeResult(username="x", films=[], watchlist_tmdb_ids=[], rating_average=None),
    )
    redis = fake_aioredis.FakeRedis(decode_responses=True)
    async with httpx.AsyncClient() as http:
        events = [e async for e in jobs.stream_build("x", redis, http, refresh=True)]

    assert events[-1]["event"] == "error"
    assert events[-1]["data"]["status"] == 422
