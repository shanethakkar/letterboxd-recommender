"""FastAPI application — Phase 0 skeleton.

Wires Redis (real or fakeredis) and a shared httpx client over the app lifespan, and
exposes a health probe plus a single-film TMDB endpoint that doubles as the end-to-end
validation surface for the Letterboxd→TMDB id mapping.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request

from backend import cache
from backend.config import get_settings
from backend.models import Film, Health
from backend.tmdb import create_tmdb_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open shared clients on startup; close them on shutdown."""
    app.state.redis = cache.create_redis()
    app.state.http = httpx.AsyncClient(timeout=10.0)
    app.state.tmdb = create_tmdb_client(app.state.http, app.state.redis)
    try:
        yield
    finally:
        await app.state.http.aclose()
        await app.state.redis.aclose()


app = FastAPI(title="Constellation API", version="0.1.0", lifespan=lifespan)


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
