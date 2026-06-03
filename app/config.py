from __future__ import annotations
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Store Intelligence Platform"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://si_user:si_password@localhost:5432/store_intelligence"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    # API
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    SECRET_KEY: str = "change-me-in-production"

    # Store defaults
    DEFAULT_STORE_ID: str = "ST1008"
    STALE_FEED_THRESHOLD_SECONDS: int = 300  # 5 minutes

    # Anomaly thresholds
    QUEUE_SPIKE_MULTIPLIER: float = 2.0
    CONVERSION_DROP_THRESHOLD: float = 0.5
    DEAD_ZONE_MINUTES: int = 30

    # POS correlation
    POS_MATCH_WINDOW_SECONDS: int = 300  # 5 minutes

    # Deduplication
    DEDUP_CACHE_SIZE: int = 10000
    DEDUP_CACHE_TTL_SECONDS: int = 3600

    # Dashboard
    DASHBOARD_REFRESH_SECONDS: int = 5

    model_config = SettingsConfigDict(env_file=".env", extra="allow")


@lru_cache
def get_settings() -> Settings:
    return Settings()
