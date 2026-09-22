"""Application configuration.

All settings are environment-driven (prefix ``CDM_``) and validated by
``pydantic-settings`` at startup. See ``.env.example`` at the repository
root for the full list of supported variables.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central, validated application settings."""

    model_config = SettingsConfigDict(
        env_prefix="CDM_",
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- Application ----
    app_name: str = "Universal GRG CDM Log Analyzer"
    version: str = "1.0.0-phase1"
    environment: str = "development"  # development | test | staging | production
    debug: bool = True
    api_prefix: str = "/api"
    cors_origins: str = "*"  # comma separated list, or "*"

    # ---- Logging ----
    log_level: str = "INFO"
    log_format: str = "json"  # json | console

    # ---- Database ----
    # MySQL in production: mysql+pymysql://user:pass@host:3306/db?charset=utf8mb4
    # SQLite is supported for local development and the test-suite.
    database_url: str = "sqlite:///./data/cdm_dev.sqlite3"
    sql_echo: bool = False

    # ---- Background processing ----
    # Leave redis_url empty to process jobs in-process (no Redis dependency).
    redis_url: str = ""
    celery_broker_url: str = ""
    celery_result_backend: str = ""
    task_eager: bool = False  # run tasks synchronously (dev/tests)

    # ---- Storage ----
    storage_dir: str = "./data"
    max_upload_size_mb: int = 200
    max_extract_size_mb: int = 1024  # total uncompressed size per ZIP
    max_extract_files: int = 500  # max files per ZIP
    allowed_upload_extensions: str = ".txt,.log,.csv,.json,.zip"

    # ---- AI explanation layer (Phase 8) ----
    # Optional OpenAI-compatible chat-completions endpoint used ONLY as an
    # explanation layer on top of the deterministic rules engine. Empty
    # base_url = no external AI; the deterministic composer is used instead.
    ai_base_url: str = ""
    ai_api_key: str = ""
    ai_model: str = ""
    ai_timeout_seconds: int = 20

    # ---- Model configuration ----
    # Directory containing per-model YAML packages (config/models/<code>/).
    # Empty = auto-discovered relative to the repository root.
    config_dir: str = ""

    # ---- Security / auth (Phase 10) ----
    # Initial ADMIN password used only when no active ADMIN exists yet.
    # CHANGE IT in production (see .env.example) — never commit real secrets.
    bootstrap_admin_password: str = "Admin#12345"
    password_min_length: int = 10
    password_hash_iterations: int = 200_000
    session_ttl_minutes: int = 480  # server-side session lifetime
    login_max_attempts: int = 5     # failed logins before temporary lockout
    login_lockout_minutes: int = 15
    trust_proxy_headers: bool = False  # honor X-Forwarded-For (behind a reverse proxy)
    # In-memory rate limits (requests/minute per IP); 0 disables a bucket.
    rate_limit_api_per_minute: int = 600
    rate_limit_auth_per_minute: int = 30
    # Archive hardening: members with these extensions are rejected; archives
    # whose per-member compression ratio exceeds the limit are treated as
    # zip bombs (on top of the total extracted-size cap).
    blocked_archive_extensions: str = ".exe,.dll,.so,.bat,.cmd,.sh,.ps1,.scr,.com"
    max_zip_compression_ratio: int = 500

    # ---- Derived helpers -------------------------------------------------

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def max_extract_size_bytes(self) -> int:
        return self.max_extract_size_mb * 1024 * 1024

    @property
    def blocked_archive_extension_set(self) -> set[str]:
        return {
            e.strip().lower() for e in self.blocked_archive_extensions.split(",") if e.strip()
        }

    @property
    def allowed_extensions(self) -> set[str]:
        return {
            e.strip().lower()
            for e in self.allowed_upload_extensions.split(",")
            if e.strip()
        }

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings singleton."""
    return Settings()
