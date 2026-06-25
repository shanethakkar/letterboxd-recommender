"""Redis cache wiring.

Local dev uses in-process `fakeredis` when `REDIS_URL` is blank; production points
`REDIS_URL` at a real Redis. Both expose the same `redis.asyncio` interface, so the
cache logic here never branches on which backend is in use — see DECISIONS.md
(2026-06-25, "Local Redis via fakeredis").
"""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis

from backend.config import get_settings


def create_redis() -> aioredis.Redis:
    """Build an async Redis client from settings.

    Real Redis when `REDIS_URL` is set, otherwise an in-process fakeredis server.
    Responses are decoded to `str` so callers get text, not bytes.
    """
    settings = get_settings()
    if settings.redis_url:
        return aioredis.from_url(settings.redis_url, decode_responses=True)

    # In-process fake; imported lazily so production images need not ship fakeredis.
    from fakeredis import aioredis as fake_aioredis

    return fake_aioredis.FakeRedis(decode_responses=True)


async def ping(client: aioredis.Redis) -> bool:
    """Return True if the Redis server responds to PING, else False."""
    try:
        return bool(await client.ping())
    except Exception:
        return False


async def get_json(client: aioredis.Redis, key: str) -> Any | None:
    """Fetch and JSON-decode a value, or None if absent."""
    raw = await client.get(key)
    return json.loads(raw) if raw is not None else None


async def set_json(
    client: aioredis.Redis, key: str, value: Any, ttl_seconds: int | None = None
) -> None:
    """JSON-encode and store a value, with an optional TTL."""
    await client.set(key, json.dumps(value), ex=ttl_seconds)
