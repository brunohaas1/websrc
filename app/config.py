import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    APP_NAME = "Personal Web Scraper Dashboard"
    DATABASE_PATH = os.getenv(
        "DATABASE_PATH",
        str(BASE_DIR / "data" / "dashboard.db"),
    )
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_JSON = os.getenv("LOG_JSON", "1") == "1"
    APP_ROLE = os.getenv("APP_ROLE", "all")

    QUEUE_ENABLED = os.getenv("QUEUE_ENABLED", "0") == "1"
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "90"))

    API_RATE_LIMIT_DEFAULT = os.getenv("API_RATE_LIMIT_DEFAULT", "120/minute")
    API_RATE_LIMIT_RUN_NOW = os.getenv("API_RATE_LIMIT_RUN_NOW", "6/minute")

    SCRAPE_INTERVAL_MINUTES = int(os.getenv("SCRAPE_INTERVAL_MINUTES", "30"))
    DAILY_INTERVAL_HOURS = int(os.getenv("DAILY_INTERVAL_HOURS", "24"))
    FEED_ENTRY_LIMIT = int(os.getenv("FEED_ENTRY_LIMIT", "30"))

    WEATHER_CITY = os.getenv("WEATHER_CITY", "Lajeado")
    WEATHER_STATE = os.getenv("WEATHER_STATE", "Rio Grande do Sul")
    WEATHER_COUNTRY_CODE = os.getenv("WEATHER_COUNTRY_CODE", "BR")
    WEATHER_LAT = float(os.getenv("WEATHER_LAT", "-29.4669"))
    WEATHER_LON = float(os.getenv("WEATHER_LON", "-51.9614"))

    AI_LOCAL_ENABLED = os.getenv("AI_LOCAL_ENABLED", "0") == "1"
    AI_LOCAL_URL = os.getenv("AI_LOCAL_URL", "http://127.0.0.1:11434")
    AI_LOCAL_MODEL = os.getenv("AI_LOCAL_MODEL", "llama3.2:3b")
    AI_LOCAL_TIMEOUT_SECONDS = int(os.getenv("AI_LOCAL_TIMEOUT_SECONDS", "25"))
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

    SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
