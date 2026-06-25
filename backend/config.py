"""Application settings, loaded from environment / `.env`.

Secrets (the TMDB key) live only in `.env` (gitignored). See `.env.example`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root is the parent of the `backend/` package, so the single root `.env`
# is found regardless of the current working directory.
_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Typed configuration for the backend."""

    model_config = SettingsConfigDict(
        env_file=_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Secrets / connections
    tmdb_api_key: str = ""
    redis_url: str | None = None

    # TMDB endpoints (rarely change; here so nothing is hardcoded deep in the client)
    tmdb_api_base: str = "https://api.themoviedb.org/3"
    tmdb_image_base: str = "https://image.tmdb.org/t/p"
    poster_size: str = "w185"

    @property
    def tmdb_key_present(self) -> bool:
        return bool(self.tmdb_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (read env/.env once per process)."""
    return Settings()
