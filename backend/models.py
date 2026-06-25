"""Pydantic models for the backend.

Phase 0 only needs `Film` (the TMDB-enriched unit). It mirrors the SPEC §4.2 extract
and will grow (ratings, feature vectors) in later phases.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Film(BaseModel):
    """A single film, hydrated from one batched TMDB call."""

    tmdb_id: int
    title: str
    year: int | None = None
    genres: list[str] = Field(default_factory=list)
    director: str | None = None
    top_cast: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    release_decade: int | None = None
    original_language: str | None = None
    runtime: int | None = None
    poster_url: str | None = None
    tmdb_recommendations: list[int] = Field(default_factory=list)
    tmdb_similar: list[int] = Field(default_factory=list)


class Health(BaseModel):
    """Response model for the `/health` endpoint."""

    status: str
    redis: str  # "ok" | "down"
    tmdb_key_present: bool
