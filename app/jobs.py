from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .services.orchestrator import ScrapeOrchestrator
from .utils import setup_logging


@dataclass
class RuntimeApp:
    config: dict


def _runtime_config(database_path: str, log_level: str) -> dict:
    return {
        "DATABASE_PATH": database_path,
        "LOG_LEVEL": log_level,
        "WEATHER_LAT": Config.WEATHER_LAT,
        "WEATHER_LON": Config.WEATHER_LON,
        "FEED_ENTRY_LIMIT": Config.FEED_ENTRY_LIMIT,
        "AI_LOCAL_ENABLED": Config.AI_LOCAL_ENABLED,
        "AI_LOCAL_BACKEND": Config.AI_LOCAL_BACKEND,
        "AI_LOCAL_URL": Config.AI_LOCAL_URL,
        "AI_LOCAL_LLAMA_CPP_CHAT_ENDPOINT": (
            Config.AI_LOCAL_LLAMA_CPP_CHAT_ENDPOINT
        ),
        "AI_LOCAL_MODEL": Config.AI_LOCAL_MODEL,
        "AI_LOCAL_TIMEOUT_SECONDS": Config.AI_LOCAL_TIMEOUT_SECONDS,
        "AI_LOCAL_RETRIES": Config.AI_LOCAL_RETRIES,
        "AI_LOCAL_BACKOFF_MS": Config.AI_LOCAL_BACKOFF_MS,
        "AI_LOCAL_CIRCUIT_FAIL_THRESHOLD": (
            Config.AI_LOCAL_CIRCUIT_FAIL_THRESHOLD
        ),
        "AI_LOCAL_CIRCUIT_OPEN_SECONDS": (
            Config.AI_LOCAL_CIRCUIT_OPEN_SECONDS
        ),
        "AI_LOCAL_ADAPTIVE_MIN_PER_RUN": Config.AI_LOCAL_ADAPTIVE_MIN_PER_RUN,
        "AI_LOCAL_MAX_ENRICH_PER_RUN": Config.AI_LOCAL_MAX_ENRICH_PER_RUN,
    }


def run_frequent_scrape(database_path: str, log_level: str = "INFO") -> None:
    setup_logging(log_level, log_json=Config.LOG_JSON)
    app = RuntimeApp(config=_runtime_config(database_path, log_level))
    orchestrator = ScrapeOrchestrator(app)
    orchestrator.run_frequent_jobs()


def run_daily_scrape(database_path: str, log_level: str = "INFO") -> None:
    setup_logging(log_level, log_json=Config.LOG_JSON)
    app = RuntimeApp(config=_runtime_config(database_path, log_level))
    orchestrator = ScrapeOrchestrator(app)
    orchestrator.run_daily_jobs()
