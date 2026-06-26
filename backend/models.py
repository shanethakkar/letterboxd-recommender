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
    # Popularity / quality signals (used in the scoring prior; SPEC §4.4).
    popularity: float | None = None
    vote_average: float | None = None
    vote_count: int | None = None
    # External review scores (OMDb: IMDb + Metacritic + Rotten Tomatoes). imdb_id is read
    # from TMDB (free); the rest are filled in by the OMDb enrichment step when available.
    imdb_id: str | None = None
    imdb_rating: float | None = None  # 0–10
    imdb_votes: int | None = None
    metascore: int | None = None  # 0–100
    rotten_tomatoes: int | None = None  # 0–100
    # Set for watched films (carried over from the scrape) — drives the taste vector.
    rating: float | None = None
    liked: bool = False


class ScrapedFilm(BaseModel):
    """A film logged on a Letterboxd profile (watched or watchlisted).

    `tmdb_id` is resolved from the Letterboxd film page (SPEC §4.1) and may be None
    if that film has no TMDB link or resolution failed.
    """

    slug: str
    tmdb_id: int | None = None
    title: str
    year: int | None = None
    rating: float | None = None  # 0.5–5.0, None if watched-but-unrated
    liked: bool = False
    in_watchlist: bool = False


class ScrapeResult(BaseModel):
    """Everything pulled for one user: watched films + watchlist (for exclusion)."""

    username: str
    films: list[ScrapedFilm] = Field(default_factory=list)  # watched
    watchlist_tmdb_ids: list[int] = Field(default_factory=list)
    rating_average: float | None = None

    def rated(self) -> list[ScrapedFilm]:
        """Watched films that carry both a rating and a resolved TMDB id."""
        return [f for f in self.films if f.rating is not None and f.tmdb_id is not None]

    def logged_tmdb_ids(self) -> set[int]:
        """All TMDB ids the user has logged (watched + watchlist) — the exclusion set."""
        ids = {f.tmdb_id for f in self.films if f.tmdb_id is not None}
        ids.update(self.watchlist_tmdb_ids)
        return ids


class Because(BaseModel):
    """One explanation edge: a watched film that pulled a recommendation toward the user."""

    id: str  # "tmdb:{id}"
    title: str
    contribution: float


class Recommendation(BaseModel):
    """A scored, explained recommendation (internal Phase 1 shape; the SPEC §5 graph
    payload is assembled in Phase 2)."""

    id: str  # "tmdb:{id}"
    tmdb_id: int
    title: str
    year: int | None = None
    score: float
    because: list[Because] = Field(default_factory=list)
    shared_traits: list[str] = Field(default_factory=list)


class Node(BaseModel):
    """A film in the constellation (SPEC §5). Watched nodes carry `rating`; recommended `score`."""

    id: str  # "tmdb:{id}"
    type: str  # "watched" | "recommended"
    title: str
    year: int | None = None
    poster_url: str | None = None
    x: float  # UMAP coord
    y: float
    cluster: int
    rating: float | None = None
    score: float | None = None
    genres: list[str] = Field(default_factory=list)
    director: str | None = None


class Edge(BaseModel):
    """A similarity edge between two nodes (SPEC §5)."""

    source: str  # "tmdb:{id}"
    target: str
    weight: float
    shared: str  # "director" | "genre" | "keyword" | "cast"


class Cluster(BaseModel):
    """A taste cluster (SPEC §5)."""

    id: int
    label: str | None = None
    centroid: list[float]  # [x, y]


class Stats(BaseModel):
    """Headline profile stats (SPEC §5)."""

    rated: int
    avg_rating: float
    clusters: int


class GraphPayload(BaseModel):
    """The full graph payload — the backend↔frontend contract (SPEC §5)."""

    username: str
    generated_at: str
    stats: Stats
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    clusters: list[Cluster] = Field(default_factory=list)


class Health(BaseModel):
    """Response model for the `/health` endpoint."""

    status: str
    redis: str  # "ok" | "down"
    tmdb_key_present: bool
