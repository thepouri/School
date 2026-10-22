"""Application settings via pydantic-settings (mirrors the Express .env)."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_user: str = "pouri"
    pg_password: str = "pouri"
    pg_database: str = "pouri"
    db_ssl: bool = False  # true for managed PG over public internet

    port: int = 3001

    # Pool settings replicated from server/src/db.js
    pool_max: int = 5
    pool_idle_timeout_s: int = 30
    statement_timeout_ms: int = 30000

    meta_cache_ttl_s: int = 300
    analytics_cache_ttl_s: int = 120
    analytics_cache_max: int = 50

    cors_origins: str = ""  # explicit allowlist for future deploys; empty = closed

    auth_jwt_secret: str = "change-me-in-production"
    auth_token_days: float = 7.0
    usage_retention_days: int = 90  # usage_log rows older than this are pruned

    @property
    def dsn(self) -> str:
        return (
            f"postgresql://{self.pg_user}:{self.pg_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_database}"
        )


settings = Settings()
