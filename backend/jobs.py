"""Streamed build (Phase 4).

`stream_build` runs `build_graph` as a background task with an async `emit` callback that pushes
`phase` + `nodes` (cascade) events onto a queue, yields them as they arrive, then emits the final
`result` (or an `error`). The SSE endpoint in `app.py` serializes these to the browser, which plays
the cascade → crystallization reveal bound to real progress.

Single build per request (KISS): the Redis cache already prevents repeat cold builds across page
loads, so a multi-subscriber job registry isn't worth the complexity yet (see DECISIONS).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

import httpx
import redis.asyncio as aioredis

from backend import scraper
from backend.graph import build_graph

logger = logging.getLogger(__name__)

# Scraper domain errors → the {status, detail} a client gets, mirroring the JSON endpoint.
_ERROR_MAP: list[tuple[type[Exception], int, str]] = [
    (scraper.UserNotFoundError, 404, "No public Letterboxd profile for '{username}'."),
    (
        scraper.PrivateProfileError,
        403,
        "This profile is private — only public diaries can be mapped.",
    ),
    (scraper.EmptyProfileError, 422, "This profile has too few rated films to build a taste map."),
    (
        scraper.AccessBlockedError,
        503,
        "Letterboxd is throttling requests right now — try again shortly.",
    ),
    (scraper.ScrapeError, 502, "Could not read that profile."),
]


def _error_event(username: str, exc: Exception) -> dict:
    for kind, status, detail in _ERROR_MAP:
        if isinstance(exc, kind):
            return {
                "event": "error",
                "data": {"status": status, "detail": detail.format(username=username)},
            }
    logger.exception("Unexpected build failure for %s", username)
    return {
        "event": "error",
        "data": {"status": 500, "detail": "Something went wrong building the map."},
    }


async def stream_build(
    username: str,
    redis: aioredis.Redis,
    http: httpx.AsyncClient,
    *,
    refresh: bool = False,
) -> AsyncIterator[dict]:
    """Yield SSE-shaped events for a streamed build: `phase`* `nodes`* then `result`|`error`."""
    queue: asyncio.Queue[dict] = asyncio.Queue()
    done = object()  # sentinel

    async def emit(event: dict) -> None:
        await queue.put(event)

    async def run() -> None:
        try:
            payload = await build_graph(username, redis, http, refresh=refresh, emit=emit)
            await queue.put({"event": "result", "data": payload.model_dump(mode="json")})
        except (
            Exception
        ) as exc:  # domain + unexpected → an error event (the SSE itself is already 200)
            await queue.put(_error_event(username, exc))
        finally:
            await queue.put(done)  # type: ignore[arg-type]

    task = asyncio.create_task(run())
    try:
        while True:
            event = await queue.get()
            if event is done:
                break
            yield event
    finally:
        if not task.done():  # client disconnected mid-build — stop the work
            task.cancel()
