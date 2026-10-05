"""Environment-driven application settings. No secrets are hard-coded."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    app_env: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"
    database_url: str = "postgresql+asyncpg://dealhunter:change-me@localhost:5432/dealhunter"
    redis_url: str = "redis://localhost:6379/0"

    # Marketplace credentials. Empty = provider not configured.
    amazon_access_key: str = ""
    amazon_secret_key: str = ""
    amazon_partner_tag: str = ""
    flipkart_affiliate_id: str = ""
    flipkart_affiliate_token: str = ""

    # None = automatic: mock providers are allowed outside production only.
    use_mock_providers: bool | None = None
    provider_requests_per_second: float = 1.0
    provider_retry_attempts: int = 3
    provider_circuit_failure_threshold: int = 5
    provider_circuit_recovery_seconds: float = 300.0

    # Auth. JWT_SECRET must be set (>= 32 chars); the API refuses to issue tokens without it.
    jwt_secret: str = ""
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    password_reset_minutes: int = 30
    frontend_url: str = "http://localhost:3000"
    rate_limit_per_minute: int = 120
    auth_rate_limit_per_minute: int = 10
    # Failed sign-ins allowed per account+IP (and 4x that per account from anywhere) in the window.
    login_failure_limit: int = 5
    login_failure_window_seconds: int = 900

    # Notification channels. A channel with no credentials is simply off; its messages wait (and expire).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_security: str = "starttls"  # starttls | ssl | none
    email_from: str = "AI Deal Hunter <no-reply@localhost>"
    telegram_bot_token: str = ""
    telegram_api_base: str = "https://api.telegram.org"
    telegram_bot_username: str = ""  # shown to users so they know which bot to message
    # Web Push (VAPID). Generate a pair with `python -m app.cli vapid-keys`.
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:admin@localhost"
    notification_max_attempts: int = 3
    sensitive_message_ttl_minutes: int = 60  # undelivered reset links are scrubbed after this long

    # Deployment / hardening
    # Number of reverse proxies in front of the API that append to X-Forwarded-For. 0 = none (trust only
    # the TCP peer). Setting this wrongly lets clients spoof their IP and dodge rate limits.
    # Per API *process*. Total connections = processes x (pool + overflow); keep it under Postgres's max_connections (100).
    db_pool_size: int = 5
    db_max_overflow: int = 10
    trusted_proxy_count: int = 0
    max_request_body_bytes: int = 1_000_000
    metrics_token: str = ""  # bearer token for /metrics; required in production, otherwise the endpoint is off

    # AI shopping assistant. Disabled until ANTHROPIC_API_KEY is set.
    anthropic_api_key: str = ""
    assistant_model: str = "claude-opus-5-5"
    assistant_effort: str = "medium"  # low | medium | high | xhigh | max
    assistant_max_tokens: int = 8000
    assistant_max_iterations: int = 6
    assistant_max_tool_calls: int = 12
    assistant_timeout_seconds: float = 120.0
    assistant_use_fallbacks: bool = True  # server-side refusal fallbacks (Claude API only)
    assistant_rate_limit_per_hour: int = 30
    mcp_server_url: str = "http://mcp-server:8765/mcp"

    # Job schedules (Celery Beat) and batching. All overridable from the environment.
    price_collection_minutes: int = 30
    catalog_sync_minutes: int = 360
    alert_check_minutes: int = 10
    notification_send_minutes: int = 5
    ranking_daily_hour_utc: int = 2
    cache_cleanup_hours: int = 6
    price_batch_size: int = 50
    job_lock_ttl_seconds: int = 1800

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host)

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token)

    @property
    def push_enabled(self) -> bool:
        return bool(self.vapid_public_key and self.vapid_private_key)

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def mock_providers_enabled(self) -> bool:
        if self.use_mock_providers is not None:
            return self.use_mock_providers
        return self.app_env.lower() != "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
