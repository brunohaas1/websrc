import logging

from flask import Flask, jsonify, render_template, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from .cache import get_cache
from .metrics import export_metrics
from .queue import get_queue
from .repository import Repository
from .security import (
    is_safe_http_url,
    sanitize_optional_selector,
    sanitize_text,
)


def register_routes(app: Flask) -> None:
    logger = logging.getLogger(__name__)
    repo = Repository(app.config["DATABASE_TARGET"])
    cache = get_cache(app.config)
    limiter = Limiter(
        key_func=get_remote_address,
        app=app,
        default_limits=[app.config["API_RATE_LIMIT_DEFAULT"]],
        storage_uri=(
            app.config["REDIS_URL"]
            if app.config["QUEUE_ENABLED"]
            else "memory://"
        ),
    )

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/health")
    @limiter.exempt
    def health():
        checks: dict = {}
        overall = "ok"

        # Postgres
        try:
            from .db import get_connection
            with get_connection(app.config["DATABASE_TARGET"]) as conn:
                conn.execute("SELECT 1")
            checks["postgres"] = "ok"
        except Exception as exc:
            checks["postgres"] = f"error: {exc}"
            overall = "degraded"

        # Redis
        if app.config["QUEUE_ENABLED"]:
            try:
                import redis as _redis
                r = _redis.from_url(app.config["REDIS_URL"])
                r.ping()
                checks["redis"] = "ok"
            except Exception as exc:
                checks["redis"] = f"error: {exc}"
                overall = "degraded"

        # LLaMA.cpp
        if app.config.get("AI_LOCAL_ENABLED"):
            try:
                import urllib.request
                url = app.config["AI_LOCAL_URL"].rstrip("/") + "/health"
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    llm_ok = resp.status == 200
                    checks["llamacpp"] = (
                        "ok" if llm_ok else f"status {resp.status}"
                    )
            except Exception as exc:
                checks["llamacpp"] = f"error: {exc}"
                overall = "degraded"

        status_code = 200 if overall == "ok" else 207
        return jsonify({"status": overall, "checks": checks}), status_code

    @app.get("/metrics")
    @limiter.exempt
    def metrics():
        return export_metrics()

    @app.get("/api/dashboard")
    def dashboard():
        cache_key = "dashboard:snapshot"
        cached = cache.get(cache_key)
        if cached is not None:
            return jsonify(cached)

        try:
            snapshot = repo.get_dashboard_snapshot()
        except Exception as exc:
            logger.exception("Falha em /api/dashboard: %s", exc)
            snapshot = {
                "news": [],
                "promotions": [],
                "prices": [],
                "weather": [],
                "tech_ai": [],
                "videos": [],
                "releases": [],
                "jobs": [],
                "alerts": [],
                "ai_observability": {
                    "window_hours": 24,
                    "total_items": 0,
                    "enriched_items": 0,
                    "enriched_percent": 0.0,
                    "avg_ai_latency_ms": None,
                    "fallback_rate_by_hour": [],
                    "source_accuracy": [],
                    "reason_breakdown": [],
                },
            }
        cache.set(cache_key, snapshot, app.config["CACHE_TTL_SECONDS"])
        return jsonify(snapshot)

    @app.get("/api/items")
    def list_items():
        item_type = request.args.get("type")
        q = request.args.get("q")
        try:
            limit = max(1, min(200, int(request.args.get("limit", "50"))))
        except (TypeError, ValueError):
            limit = 50
        cache_key = f"items:{item_type}:{q}:{limit}"
        cached = cache.get(cache_key)
        if cached is not None:
            return jsonify(cached)

        try:
            items = repo.list_items(item_type=item_type, limit=limit, q=q)
        except Exception as exc:
            logger.exception("Falha em /api/items: %s", exc)
            items = []
        cache.set(cache_key, items, app.config["CACHE_TTL_SECONDS"])
        return jsonify(items)

    @app.get("/api/ai-observability")
    def ai_observability():
        cache_key = "ai:observability"
        cached = cache.get(cache_key)
        if cached is not None:
            return jsonify(cached)

        payload = repo.get_ai_observability()
        cache.set(cache_key, payload, app.config["CACHE_TTL_SECONDS"])
        return jsonify(payload)

    @app.post("/api/price-watch")
    @limiter.limit("20/minute")
    def add_price_watch():
        payload = request.get_json(force=True)
        required = ["name", "product_url", "target_price"]
        missing = [key for key in required if key not in payload]
        if missing:
            message = f"Campos ausentes: {', '.join(missing)}"
            return jsonify({"error": message}), 400

        product_url = str(payload.get("product_url", "")).strip()
        if not is_safe_http_url(product_url):
            return jsonify({"error": "URL inválida. Use http/https."}), 400

        try:
            target_price = float(payload.get("target_price"))
        except (TypeError, ValueError):
            return jsonify({"error": "target_price inválido"}), 400

        sanitized_payload = {
            "name": sanitize_text(str(payload.get("name", "")), 120),
            "product_url": product_url,
            "css_selector": sanitize_optional_selector(
                payload.get("css_selector"),
            ),
            "target_price": target_price,
            "currency": sanitize_text(str(payload.get("currency", "BRL")), 12),
        }

        watch_id = repo.add_price_watch(sanitized_payload)
        return jsonify({"ok": True, "id": watch_id}), 201

    @app.get("/api/price-history/<int:watch_id>")
    def price_history(watch_id: int):
        return jsonify(repo.get_price_history(watch_id))

    @app.post("/api/run-now")
    @limiter.limit(app.config["API_RATE_LIMIT_RUN_NOW"])
    def run_now():
        queue = get_queue(app.config)
        if queue is not None:
            from .jobs import run_daily_scrape, run_frequent_scrape

            frequent = queue.enqueue(
                run_frequent_scrape,
                app.config["DATABASE_TARGET"],
                app.config["LOG_LEVEL"],
                job_timeout="10m",
            )
            daily = queue.enqueue(
                run_daily_scrape,
                app.config["DATABASE_TARGET"],
                app.config["LOG_LEVEL"],
                job_timeout="20m",
            )
            return jsonify(
                {
                    "ok": True,
                    "mode": "queued",
                    "jobs": [frequent.id, daily.id],
                }
            )

        scheduler = getattr(app, "scheduler", None)
        if scheduler is None:
            return jsonify({"error": "Scheduler não inicializado"}), 503

        scheduler.run_all_now()
        return jsonify({"ok": True, "message": "Coleta executada."})

    @app.post("/api/maintenance/ai-backfill")
    @limiter.limit("2/day")
    def ai_backfill_once():
        try:
            batch_size = max(
                1,
                min(500, int(request.args.get("batch_size", "80"))),
            )
        except (TypeError, ValueError):
            batch_size = 80
        try:
            max_cycles = max(
                1,
                min(500, int(request.args.get("max_cycles", "120"))),
            )
        except (TypeError, ValueError):
            max_cycles = 120

        queue = get_queue(app.config)
        if queue is not None:
            from .jobs import run_ai_backfill_once

            job = queue.enqueue(
                run_ai_backfill_once,
                app.config["DATABASE_TARGET"],
                app.config["LOG_LEVEL"],
                batch_size,
                max_cycles,
                job_timeout="60m",
            )
            cache.delete("dashboard:snapshot")
            cache.delete("ai:observability")
            return jsonify(
                {
                    "ok": True,
                    "mode": "queued",
                    "job": job.id,
                    "batch_size": batch_size,
                    "max_cycles": max_cycles,
                }
            )

        from .jobs import run_ai_backfill_once

        payload = run_ai_backfill_once(
            app.config["DATABASE_TARGET"],
            app.config["LOG_LEVEL"],
            batch_size,
            max_cycles,
        )
        cache.delete("dashboard:snapshot")
        cache.delete("ai:observability")
        return jsonify({"ok": True, "mode": "sync", **payload})

    @app.post("/api/maintenance/cleanup-summaries")
    @limiter.limit("2/day")
    def cleanup_summaries():
        payload = repo.cleanup_duplicate_summaries()
        cache.delete("dashboard:snapshot")
        cache.delete("ai:observability")
        return jsonify({"ok": True, **payload})
