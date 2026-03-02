from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .repository import Repository
from .services.ai_enrichment_service import LocalAIEnricher
from .services.orchestrator import ScrapeOrchestrator
from .utils import setup_logging


@dataclass
class RuntimeApp:
    config: dict


def _runtime_config(database_target: str, log_level: str) -> dict:
    return {
        "DATABASE_TARGET": database_target,
        "DATABASE_PATH": database_target,
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


def run_frequent_scrape(database_target: str, log_level: str = "INFO") -> None:
    setup_logging(log_level, log_json=Config.LOG_JSON)
    app = RuntimeApp(config=_runtime_config(database_target, log_level))
    orchestrator = ScrapeOrchestrator(app)
    orchestrator.run_frequent_jobs()


def run_daily_scrape(database_target: str, log_level: str = "INFO") -> None:
    setup_logging(log_level, log_json=Config.LOG_JSON)
    app = RuntimeApp(config=_runtime_config(database_target, log_level))
    orchestrator = ScrapeOrchestrator(app)
    orchestrator.run_daily_jobs()


def run_ai_backfill_once(
    database_target: str,
    log_level: str = "INFO",
    batch_size: int = 80,
    max_cycles: int = 120,
) -> dict:
    setup_logging(log_level, log_json=Config.LOG_JSON)

    runtime_config = _runtime_config(database_target, log_level)
    runtime_config["AI_LOCAL_MAX_ENRICH_PER_RUN"] = int(batch_size)
    runtime_config["AI_LOCAL_ADAPTIVE_MIN_PER_RUN"] = max(
        5,
        min(int(batch_size), int(batch_size // 2) or 1),
    )

    app = RuntimeApp(config=runtime_config)
    repo = Repository(database_target)
    enricher = LocalAIEnricher(app)

    scanned = 0
    updated = 0
    model_count = 0
    fallback_count = 0

    for _ in range(max_cycles):
        pending = repo.list_pending_ai_items(limit=batch_size)
        if not pending:
            break

        for item in pending:
            scanned += 1

            if not enricher.should_enrich(item):
                continue

            enriched = enricher.enrich_item(item)
            extra = enriched.get("extra")
            if not isinstance(extra, dict):
                continue

            repo.update_item_extra(int(item.get("id") or 0), extra)
            updated += 1

            ai_stage = str(extra.get("ai_stage") or "").strip().lower()
            if ai_stage == "model":
                model_count += 1
            elif ai_stage == "fallback":
                fallback_count += 1

        if len(pending) < batch_size:
            break

    return {
        "scanned": scanned,
        "updated": updated,
        "model": model_count,
        "fallback": fallback_count,
        "batch_size": int(batch_size),
        "max_cycles": int(max_cycles),
    }
