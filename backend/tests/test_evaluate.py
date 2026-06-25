"""Eval harness: end-to-end on a synthetic profile (scraper + TMDB faked, no network)."""

import fakeredis.aioredis as fake_aioredis

import backend.evaluate as ev
from backend.models import Film, ScrapedFilm, ScrapeResult

LOVED = list(range(1, 13))  # 12 loved films, tmdb ids 1..12


class _FakeTMDB:
    async def get_movies(self, ids, **_kw) -> dict[int, Film]:
        return {
            i: Film(
                tmdb_id=i,
                title=f"F{i}",
                genres=["Action"],
                vote_count=1000,  # clears the vote floor
                vote_average=7.0,
                year=2015,
                # each film recommends every other loved film → held-out films are reachable
                tmdb_recommendations=[j for j in LOVED if j != i],
            )
            for i in ids
        }

    async def discover_backfill(self, **_kw) -> list[int]:
        return []


async def test_evaluate_returns_valid_metrics_and_reaches_heldout(monkeypatch) -> None:
    rated = [ScrapedFilm(slug=f"f{i}", tmdb_id=i, title=f"F{i}", rating=5.0) for i in LOVED]
    result_obj = ScrapeResult(username="x", films=rated, watchlist_tmdb_ids=[], rating_average=5.0)

    async def fake_scrape(username, redis, **_kw):
        return result_obj

    monkeypatch.setattr(ev.scraper, "scrape_user", fake_scrape)
    monkeypatch.setattr(ev, "create_tmdb_client", lambda http: _FakeTMDB())
    monkeypatch.setattr(ev, "create_redis", lambda: fake_aioredis.FakeRedis(decode_responses=True))

    result = await ev.evaluate("x", n_clusters=1, n_splits=2)

    assert result is not None
    assert all(0.0 <= v <= 1.0 for v in result.values())  # all metrics are fractions
    # Held-out films are recommended by the kept seeds, so they're reachable in the pool.
    assert result["pool_recall"] > 0.0
