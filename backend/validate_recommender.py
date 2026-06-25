"""Phase 1 validation entrypoint (SPEC §7, Phase 1).

Runs the full recommender pipeline against a real Letterboxd profile and prints the top
recommendations with their "why" for a human gut-check:

    uv run python -m backend.validate_recommender sthakkar

First run warms the permanent slug→tmdb_id cache and is the slow one; re-runs are fast.
"""

from __future__ import annotations

import asyncio
import statistics
import sys
import time

import httpx

from backend import scraper
from backend.cache import create_redis
from backend.models import Film
from backend.recommender import recommend
from backend.tmdb import build_candidate_pool, create_tmdb_client

SEED_LIMIT = 40  # top-rated films whose TMDB recs/similar seed the candidate pool
SEED_MIN_RATING = 4.0
MAX_CANDIDATES = 600  # cap enrichment + MMR cost
TOP_N = 20


async def run(username: str) -> None:
    redis = create_redis()
    async with httpx.AsyncClient(timeout=15.0) as http:
        tmdb = create_tmdb_client(http)

        # 1. Scrape ------------------------------------------------------------
        t = time.perf_counter()
        try:
            scrape = await scraper.scrape_user(username, redis)
        except scraper.ScrapeError as exc:
            print(f"\n  Cannot map @{username}: {type(exc).__name__} — {exc}")
            await redis.aclose()
            return
        rated = scrape.rated()
        user_mean = scrape.rating_average or (
            sum(f.rating for f in rated) / len(rated) if rated else 0.0
        )
        print(
            f"\n  @{scrape.username}: {len(scrape.films)} films, {len(rated)} rated "
            f"(avg {user_mean:.2f}) — scraped in {time.perf_counter() - t:.0f}s"
        )
        if not rated:
            print("  Too few rated films with TMDB ids to build a taste profile.")
            await redis.aclose()
            return

        # 2. Enrich watched films via TMDB ------------------------------------
        t = time.perf_counter()
        watched_map = await tmdb.get_movies([f.tmdb_id for f in rated])
        watched: list[Film] = []
        for sf in rated:
            film = watched_map.get(sf.tmdb_id)
            if film is None:
                continue
            film.rating, film.liked = sf.rating, sf.liked
            watched.append(film)
        print(f"  enriched {len(watched)} watched films in {time.perf_counter() - t:.0f}s")

        # 3. Build + enrich candidate pool ------------------------------------
        t = time.perf_counter()
        seeds = sorted(watched, key=lambda f: f.rating or 0.0, reverse=True)
        top_seeds = [f for f in seeds if (f.rating or 0) >= SEED_MIN_RATING][:SEED_LIMIT]
        top_seeds = top_seeds or seeds[:SEED_LIMIT]
        backfill = await tmdb.discover_backfill()
        provenance_map = build_candidate_pool(top_seeds, scrape.logged_tmdb_ids(), backfill)
        ranked = sorted(provenance_map.items(), key=lambda kv: kv[1], reverse=True)[:MAX_CANDIDATES]

        cand_map = await tmdb.get_movies([cid for cid, _ in ranked])
        candidates: list[Film] = []
        provenance: list[int] = []
        for cid, prov in ranked:
            film = cand_map.get(cid)
            if film is not None:
                candidates.append(film)
                provenance.append(prov)
        print(
            f"  candidate pool: {len(candidates)} films "
            f"(from {len(top_seeds)} seeds + backfill) in {time.perf_counter() - t:.0f}s"
        )

        # 4. Recommend --------------------------------------------------------
        recs = recommend(watched, candidates, provenance, user_mean=user_mean, top_n=TOP_N)

    await redis.aclose()

    # 5. Print for gut-check --------------------------------------------------
    rec_films = [cand_map[r.tmdb_id] for r in recs if r.tmdb_id in cand_map]
    med_votes = int(statistics.median([f.vote_count or 0 for f in rec_films])) if rec_films else 0
    years = [f.year for f in rec_films if f.year]
    mean_year = int(statistics.mean(years)) if years else 0
    print(
        f"\n  TOP {len(recs)} RECOMMENDATIONS for @{scrape.username}"
        f"   (median TMDB votes: {med_votes:,} · mean year: {mean_year})\n  " + "─" * 60
    )
    for i, r in enumerate(recs, 1):
        year = f" ({r.year})" if r.year else ""
        print(f"\n  {i:>2}. {r.title}{year}   score={r.score:.3f}")
        if r.shared_traits:
            print(f"      traits: {', '.join(r.shared_traits)}")
        if r.because:
            seeds_txt = "; ".join(f"{b.title} ({b.contribution:.2f})" for b in r.because)
            print(f"      because you rated: {seeds_txt}")


def main() -> None:
    # Film titles (and our separators) are non-ASCII; the Windows console defaults to
    # cp1252. Force UTF-8 so printing never crashes on "Amélie" or a box-drawing rule.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    username = sys.argv[1] if len(sys.argv) > 1 else "sthakkar"
    asyncio.run(run(username))


if __name__ == "__main__":
    main()
