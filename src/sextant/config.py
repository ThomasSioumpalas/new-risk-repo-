"""Runtime configuration from environment variables (12-factor).

All settings use the ``SEXTANT_`` prefix. Secrets are never read from files in
the repository.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SEXTANT_", env_file=None, extra="ignore")

    env: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite:///./sextant.db"
    log_level: str = "INFO"
    log_json: bool = True
    # Upper bound on Monte Carlo trials accepted through the API (resource-exhaustion guard).
    api_max_trials: int = Field(default=50_000, ge=1_000, le=200_000)
    # Upper bound on simulated loss events per API request (memory guard).
    api_max_events: int = Field(default=2_000_000, ge=10_000)


@lru_cache
def get_settings() -> Settings:
    return Settings()
