"""Phase 2 evidence: build, serialize, and eyeball the graph payload (SPEC §5).

    uv run python -m backend.validate_graph sthakkar

Prints a summary and writes the full JSON to a gitignored `graph-<user>.json`.
"""

from __future__ import annotations

import asyncio
import json
import sys

import httpx

from backend.cache import create_redis
from backend.graph import build_graph


async def run(username: str) -> None:
    redis = create_redis()
    async with httpx.AsyncClient(timeout=15.0) as http:
        payload = await build_graph(username, redis, http, refresh=True)
        cached = await build_graph(username, redis, http)  # 2nd build → should hit cache
    await redis.aclose()

    out_path = f"graph-{username}.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload.model_dump(mode="json"), fh, indent=2, ensure_ascii=False)

    watched = [n for n in payload.nodes if n.type == "watched"]
    recs = [n for n in payload.nodes if n.type == "recommended"]
    print(f"\n  GRAPH @{payload.username}  (generated {payload.generated_at})")
    print(f"  nodes: {len(payload.nodes)} ({len(watched)} watched + {len(recs)} recommended)")
    print(
        f"  edges: {len(payload.edges)}   clusters: {len(payload.clusters)}   "
        f"recs: {len(payload.recommendations)}"
    )
    print(
        f"  stats: rated={payload.stats.rated} "
        f"avg={payload.stats.avg_rating} clusters={payload.stats.clusters}"
    )
    print("\n  clusters (auto-labelled by dominant genre):")
    for c in payload.clusters:
        size = sum(1 for n in payload.nodes if n.cluster == c.id)
        print(f"    [{c.id}] {c.label or '—':<22} {size:>3} nodes")
    print("\n  sample similarity edges:")
    for e in payload.edges[:6]:
        print(f"    {e.source} — {e.target}   w={e.weight}  ({e.shared})")
    print(f"\n  cache hit on 2nd build: {cached.generated_at == payload.generated_at}")
    print(f"  full JSON → {out_path}")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    username = sys.argv[1] if len(sys.argv) > 1 else "sthakkar"
    asyncio.run(run(username))


if __name__ == "__main__":
    main()
