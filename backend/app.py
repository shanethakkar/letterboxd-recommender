"""FastAPI application.

Wires Redis (real or fakeredis) and a shared httpx client over the app lifespan, and exposes:
`/health`, `/api/films/{id}` (TMDB id-mapping probe), and `/api/graph/{username}` (the SPEC §5
graph payload the frontend renders).
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from backend import cache, scraper
from backend.config import get_settings
from backend.graph import build_graph
from backend.jobs import stream_build
from backend.models import Film, GraphPayload, Health
from backend.tmdb import create_tmdb_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open shared clients on startup; close them on shutdown."""
    app.state.redis = cache.create_redis()
    app.state.http = httpx.AsyncClient(timeout=15.0)
    app.state.tmdb = create_tmdb_client(app.state.http, app.state.redis)
    try:
        yield
    finally:
        await app.state.http.aclose()
        await app.state.redis.aclose()


app = FastAPI(title="Constellation API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list({get_settings().frontend_origin, "http://localhost:3000"}),
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health", response_model=Health)
async def health(request: Request) -> Health:
    """Liveness probe: reports Redis connectivity and whether the TMDB key is configured."""
    redis_ok = await cache.ping(request.app.state.redis)
    settings = get_settings()
    return Health(
        status="ok",
        redis="ok" if redis_ok else "down",
        tmdb_key_present=settings.tmdb_key_present,
    )


@app.get("/api/films/{tmdb_id}", response_model=Film)
async def get_film(tmdb_id: int, request: Request) -> Film:
    """Return one TMDB-enriched film. Validates the key + id mapping end-to-end."""
    if not get_settings().tmdb_key_present:
        raise HTTPException(
            status_code=503,
            detail="TMDB_API_KEY is not set. Paste your key into .env and restart.",
        )
    try:
        return await request.app.state.tmdb.get_movie(tmdb_id)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 404:
            raise HTTPException(404, detail=f"No TMDB film with id {tmdb_id}.") from exc
        if status in (401, 403):
            raise HTTPException(502, detail="TMDB rejected the API key.") from exc
        raise HTTPException(502, detail=f"TMDB error ({status}).") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, detail="Could not reach TMDB.") from exc


@app.get("/api/graph/{username}", response_model=GraphPayload)
async def get_graph(username: str, request: Request, refresh: bool = False) -> GraphPayload:
    """The full constellation payload for a user (cache-first; `?refresh=true` rebuilds).

    Cold builds scrape + score and can take minutes; warm cache returns instantly. (Phase 4
    turns the cold path into a streamed four-act experience.)
    """
    try:
        return await build_graph(
            username, request.app.state.redis, request.app.state.http, refresh=refresh
        )
    except scraper.UserNotFoundError as exc:
        raise HTTPException(404, detail=f"No public Letterboxd profile for '{username}'.") from exc
    except scraper.PrivateProfileError as exc:
        raise HTTPException(
            403, detail="This profile is private — only public diaries can be mapped."
        ) from exc
    except scraper.EmptyProfileError as exc:
        raise HTTPException(
            422, detail="This profile has too few rated films to build a taste map."
        ) from exc
    except scraper.AccessBlockedError as exc:
        raise HTTPException(
            503, detail="Letterboxd is throttling requests right now — try again shortly."
        ) from exc
    except scraper.ScrapeError as exc:
        raise HTTPException(502, detail=f"Could not read that profile: {exc}") from exc


@app.get("/api/graph/{username}/stream")
async def stream_graph(
    username: str, request: Request, refresh: bool = False
) -> EventSourceResponse:
    """Server-Sent Events for a streamed build (Phase 4): `phase` + `nodes` (poster cascade) →
    `result` (full payload) or `error`. A cache hit emits `result` immediately. Domain errors
    arrive as an `error` event (the SSE response itself is already 200)."""

    async def events():
        async for event in stream_build(
            username, request.app.state.redis, request.app.state.http, refresh=refresh
        ):
            yield {"event": event["event"], "data": json.dumps(event["data"])}

    return EventSourceResponse(events())
