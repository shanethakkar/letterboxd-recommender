"""Leave-one-out evaluation harness (SPEC §4.7).

Quantifies recommender accuracy so "more accurate" is a number, not a vibe. Hold out a
fraction of the user's highly-rated films, build the recommender from the rest, and measure
whether the held-out films are (a) *reachable* in the candidate pool and (b) ranked into the
top-K. Compare models (e.g. single-centroid vs multi-centroid) on the same splits:

    uv run python -m backend.evaluate sthakkar
    uv run python -m backend.evaluate sthakkar --clusters 5

OMDb is intentionally skipped here — this measures retrieval/ranking from taste, not review polish.
"""

from __future__ import annotations

import asyncio
import random
import statistics
import sys

import httpx

from backend import scraper
from backend.cache import create_redis
from backend.models import Film
from backend.recommender import recommend
from backend.tmdb import TMDBClient, build_candidate_pool, create_tmdb_client

HOLD_THRESHOLD = 4.5  # "loved" films we try to predict
HOLD_FRACTION = 0.25
N_SPLITS = 3
EVAL_TOP_N = 100  # rank this many, then measure recall at several cut-offs
RECALL_KS = (20, 50, 100)
SEED_MIN_RATING = 4.0
SEED_MAX = 150
MAX_CANDIDATES = 500


async def _get_movies_memo(
    tmdb: TMDBClient, ids: list[int], memo: dict[int, Film]
) -> dict[int, Film]:
    """Fetch only ids not already enriched this run (splits share a candidate memo)."""
    missing = [i for i in ids if i not in memo]
    if missing:
        memo.update(await tmdb.get_movies(missing))
    return {i: memo[i] for i in ids if i in memo}


async def evaluate(
    username: str, *, n_clusters: int = 1, n_splits: int = N_SPLITS
) -> dict[str, float] | None:
    redis = create_redis()
    memo: dict[int, Film] = {}
    async with httpx.AsyncClient(timeout=15.0) as http:
        tmdb = create_tmdb_client(http)
        scrape = await scraper.scrape_user(username, redis)
        rated = scrape.rated()
        if not rated:
            print(f"  @{username}: no rated films with TMDB ids.")
            await redis.aclose()
            return None
        user_mean = scrape.rating_average or (sum(f.rating for f in rated) / len(rated))

        watched_map = await _get_movies_memo(tmdb, [f.tmdb_id for f in rated], memo)
        watched: list[Film] = []
        for sf in rated:
            film = watched_map.get(sf.tmdb_id)
            if film is None:
                continue
            film.rating, film.liked = sf.rating, sf.liked
            watched.append(film)

        positives = [f.tmdb_id for f in watched if (f.rating or 0) >= HOLD_THRESHOLD]
        if len(positives) < 8:
            print(f"  Only {len(positives)} films rated ≥{HOLD_THRESHOLD}; too few to evaluate.")
            await redis.aclose()
            return None

        logged = scrape.logged_tmdb_ids()
        backfill = await tmdb.discover_backfill()
        rng = random.Random(0)
        hold_n = max(1, round(len(positives) * HOLD_FRACTION))
        pool_recalls: list[float] = []
        recalls: dict[int, list[float]] = {k: [] for k in RECALL_KS}

        for _ in range(n_splits):
            test = set(rng.sample(positives, k=hold_n))
            train = [f for f in watched if f.tmdb_id not in test]
            train_seeds = [
                f
                for f in sorted(train, key=lambda f: f.rating or 0.0, reverse=True)
                if (f.rating or 0) >= SEED_MIN_RATING
            ][:SEED_MAX]

            # Exclude everything logged EXCEPT the held-out films, so they *can* be recommended.
            prov_map = build_candidate_pool(train_seeds, logged - test, backfill)
            ranked = sorted(prov_map.items(), key=lambda kv: kv[1], reverse=True)[:MAX_CANDIDATES]
            cand_map = await _get_movies_memo(tmdb, [cid for cid, _ in ranked], memo)
            candidates: list[Film] = []
            provenance: list[int] = []
            for cid, prov in ranked:
                if cid in cand_map:
                    candidates.append(cand_map[cid])
                    provenance.append(prov)
            cand_ids = {f.tmdb_id for f in candidates}

            recs = recommend(
                train,
                candidates,
                provenance,
                user_mean=user_mean,
                top_n=EVAL_TOP_N,
                n_clusters=n_clusters,
            )
            ranked_ids = [r.tmdb_id for r in recs]

            pool_recalls.append(len(test & cand_ids) / len(test))
            for k in RECALL_KS:
                recalls[k].append(len(test & set(ranked_ids[:k])) / len(test))

    await redis.aclose()

    result = {
        "pool_recall": statistics.mean(pool_recalls),
        **{f"recall@{k}": statistics.mean(recalls[k]) for k in RECALL_KS},
    }
    print(
        f"\n  EVAL @{username}  (clusters={n_clusters}, splits={n_splits}, "
        f"hold≥{HOLD_THRESHOLD}, ~{hold_n}/{len(positives)} held out/split)"
    )
    print(f"  pool-recall@{MAX_CANDIDATES}: {result['pool_recall']:.1%}   (reachable in pool)")
    for k in RECALL_KS:
        print(f"  recall@{k:<3}        {result[f'recall@{k}']:.1%}   (ranked into top-{k})")
    return result


def _parse_args(argv: list[str]) -> tuple[str, int]:
    username, n_clusters, rest = "sthakkar", 1, []
    i = 0
    while i < len(argv):
        if argv[i] == "--clusters" and i + 1 < len(argv):
            n_clusters, i = int(argv[i + 1]), i + 2
        else:
            rest.append(argv[i])
            i += 1
    if rest:
        username = rest[0]
    return username, n_clusters


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    username, n_clusters = _parse_args(sys.argv[1:])
    asyncio.run(evaluate(username, n_clusters=n_clusters))


if __name__ == "__main__":
    main()
