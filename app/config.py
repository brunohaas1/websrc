import os
import secrets
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    APP_NAME = "Personal Web Scraper Dashboard"
    DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
    DATABASE_PATH = os.getenv(
        "DATABASE_PATH",
        str(BASE_DIR / "data" / "dashboard.db"),
    )
    DATABASE_TARGET = DATABASE_URL or DATABASE_PATH
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_JSON = os.getenv("LOG_JSON", "1") == "1"
    APP_ROLE = os.getenv("APP_ROLE", "all")

    QUEUE_ENABLED = os.getenv("QUEUE_ENABLED", "0") == "1"
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "90"))

    API_RATE_LIMIT_DEFAULT = os.getenv("API_RATE_LIMIT_DEFAULT", "120/minute")
    API_RATE_LIMIT_RUN_NOW = os.getenv("API_RATE_LIMIT_RUN_NOW", "6/minute")

    SCRAPE_INTERVAL_MINUTES = max(
        1,
        int(os.getenv("SCRAPE_INTERVAL_MINUTES", "30")),
    )
    DAILY_INTERVAL_HOURS = max(
        1,
        int(os.getenv("DAILY_INTERVAL_HOURS", "24")),
    )
    FEED_ENTRY_LIMIT = int(os.getenv("FEED_ENTRY_LIMIT", "30"))

    WEATHER_CITY = os.getenv("WEATHER_CITY", "Lajeado")
    WEATHER_STATE = os.getenv("WEATHER_STATE", "Rio Grande do Sul")
    WEATHER_COUNTRY_CODE = os.getenv("WEATHER_COUNTRY_CODE", "BR")
    WEATHER_LAT = float(os.getenv("WEATHER_LAT", "-29.4669"))
    WEATHER_LON = float(os.getenv("WEATHER_LON", "-51.9614"))

    AI_LOCAL_ENABLED = os.getenv("AI_LOCAL_ENABLED", "0") == "1"
    AI_LOCAL_BACKEND = os.getenv("AI_LOCAL_BACKEND", "ollama")
    AI_LOCAL_URL = os.getenv("AI_LOCAL_URL", "http://127.0.0.1:11434")
    AI_LOCAL_LLAMA_CPP_CHAT_ENDPOINT = os.getenv(
        "AI_LOCAL_LLAMA_CPP_CHAT_ENDPOINT",
        "/v1/chat/completions",
    )
    AI_LOCAL_MODEL = os.getenv("AI_LOCAL_MODEL", "qwen2.5:7b-instruct")
    AI_LOCAL_TIMEOUT_SECONDS = int(os.getenv("AI_LOCAL_TIMEOUT_SECONDS", "30"))
    AI_LOCAL_RETRIES = int(os.getenv("AI_LOCAL_RETRIES", "2"))
    AI_LOCAL_BACKOFF_MS = int(os.getenv("AI_LOCAL_BACKOFF_MS", "400"))
    AI_LOCAL_CIRCUIT_FAIL_THRESHOLD = int(
        os.getenv("AI_LOCAL_CIRCUIT_FAIL_THRESHOLD", "3"),
    )
    AI_LOCAL_CIRCUIT_OPEN_SECONDS = int(
        os.getenv("AI_LOCAL_CIRCUIT_OPEN_SECONDS", "120"),
    )
    AI_LOCAL_ADAPTIVE_MIN_PER_RUN = int(
        os.getenv("AI_LOCAL_ADAPTIVE_MIN_PER_RUN", "4"),
    )
    AI_LOCAL_MAX_ENRICH_PER_RUN = int(
        os.getenv("AI_LOCAL_MAX_ENRICH_PER_RUN", "12"),
    )

    SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_hex(32)
    ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "").strip()

    DATA_RETENTION_DAYS = int(os.getenv("DATA_RETENTION_DAYS", "90"))

    # ── Currency Widget ──────────────────────────────────────
    CURRENCY_API_URL = os.getenv(
        "CURRENCY_API_URL",
        "https://economia.awesomeapi.com.br/last/USD-BRL,EUR-BRL,BTC-BRL",
    )
    CURRENCY_UPDATE_MINUTES = int(os.getenv("CURRENCY_UPDATE_MINUTES", "15"))

    # ── Service Monitor ──────────────────────────────────────
    SERVICE_MONITOR_INTERVAL_MINUTES = int(
        os.getenv("SERVICE_MONITOR_INTERVAL_MINUTES", "5"),
    )

    # ── Web Push (VAPID) ─────────────────────────────────────
    VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "").strip()
    VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "").strip()
    VAPID_CLAIMS_EMAIL = os.getenv(
        "VAPID_CLAIMS_EMAIL", "mailto:admin@localhost",
    )

    # ── i18n ─────────────────────────────────────────────────
    DEFAULT_LOCALE = os.getenv("DEFAULT_LOCALE", "pt-BR")

    # ── PDF Export ───────────────────────────────────────────
    PDF_EXPORT_ENABLED = os.getenv("PDF_EXPORT_ENABLED", "0") == "1"

    # ── Shareable Dashboard ──────────────────────────────────
    SHARE_TOKEN_SECRET = os.getenv("SHARE_TOKEN_SECRET", "") or secrets.token_hex(16)
    SHARE_LINK_EXPIRY_HOURS = int(os.getenv("SHARE_LINK_EXPIRY_HOURS", "72"))

    # ── Email Digest (SMTP) ──────────────────────────────────
    SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER = os.getenv("SMTP_USER", "").strip()
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
    SMTP_FROM = os.getenv("SMTP_FROM", "").strip()
    EMAIL_DIGEST_RECIPIENTS = os.getenv("EMAIL_DIGEST_RECIPIENTS", "").strip()
    SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "1") == "1"

    # ── Webhook Outbound ─────────────────────────────────────
    WEBHOOK_TIMEOUT_SECONDS = int(os.getenv("WEBHOOK_TIMEOUT_SECONDS", "10"))
    WEBHOOK_MAX_RETRIES = int(os.getenv("WEBHOOK_MAX_RETRIES", "3"))
