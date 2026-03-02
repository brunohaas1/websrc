import logging
import time
import queue as _queue
from datetime import datetime, timezone

import feedparser
import requests as http_requests
from flask import Flask, Response, jsonify, render_template, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from .cache import get_cache
from .db import get_connection
from .metrics import export_metrics
from .queue import get_queue
from .repository import Repository
from .security import (
    is_safe_http_url,
    require_admin_key,
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

    @app.get("/api/llm-status")
    @limiter.limit("15/minute")
    def llm_status():
        """Lightweight LLM health probe for the dashboard indicator."""
        if not app.config.get("AI_LOCAL_ENABLED"):
            return jsonify({"status": "disabled", "detail": "AI_LOCAL_ENABLED=0"})
        try:
            import urllib.request, json as _json
            url = app.config["AI_LOCAL_URL"].rstrip("/") + "/health"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                body = _json.loads(resp.read())
                ok = resp.status == 200
                return jsonify({
                    "status": "ok" if ok else "degraded",
                    "http_status": resp.status,
                    "detail": body,
                })
        except Exception as exc:
            return jsonify({"status": "error", "detail": str(exc)})

    # ── Server-Sent Events (SSE) ───────────────────────────
    _sse_clients: list[_queue.Queue] = []

    @app.get("/api/stream")
    @limiter.limit("5/minute")
    def sse_stream():
        """SSE endpoint: pushes real-time events to connected clients."""
        q: _queue.Queue = _queue.Queue(maxsize=50)
        _sse_clients.append(q)

        def generate():
            try:
                yield "data: {\"type\":\"connected\"}\n\n"
                while True:
                    try:
                        msg = q.get(timeout=30)
                        yield f"data: {msg}\n\n"
                    except _queue.Empty:
                        yield ": keepalive\n\n"
            except GeneratorExit:
                pass
            finally:
                if q in _sse_clients:
                    _sse_clients.remove(q)

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    def broadcast_sse(event_data: str) -> None:
        """Send an event to all connected SSE clients."""
        dead = []
        for q in _sse_clients:
            try:
                q.put_nowait(event_data)
            except _queue.Full:
                dead.append(q)
        for q in dead:
            if q in _sse_clients:
                _sse_clients.remove(q)

    # Attach broadcast to app for use in other modules
    app.broadcast_sse = broadcast_sse  # type: ignore[attr-defined]

    # ── Smart Alerts (AI-powered) ───────────────────────────

    @app.post("/api/smart-alerts/analyze")
    @limiter.limit("3/minute")
    def smart_alerts_analyze():
        """Run AI smart alert analysis on the current dashboard snapshot."""
        import json as _json
        from .services.smart_alerts_service import SmartAlertAnalyzer

        # Get cached snapshot
        cached = cache.get("dashboard:snapshot")
        if cached:
            snapshot = cached
        else:
            snapshot = repo.get_dashboard_snapshot()

        analyzer = SmartAlertAnalyzer(app.config)
        alerts = analyzer.analyze(snapshot)

        # Persist each alert
        for alert in alerts:
            repo.create_alert(
                alert_type=alert.get("type", "info"),
                title=alert.get("title", ""),
                message=alert.get("message", ""),
                payload={"ai_reason": alert.get("ai_reason", ""), "source": alert.get("source", "")},
            )

        # Broadcast via SSE
        if alerts:
            broadcast_sse(_json.dumps({"type": "smart_alert", "alerts": alerts}))

        cache.delete("dashboard:snapshot")
        return jsonify({"ok": True, "alerts": alerts, "count": len(alerts)})

    @app.get("/metrics")
    @limiter.exempt
    def metrics():
        return export_metrics()

    @app.get("/api/dashboard")
    @limiter.limit("60/minute")
    def dashboard():
        cache_key = "dashboard:snapshot"
        cached = cache.get(cache_key)
        if cached is not None:
            return jsonify(cached)

        try:
            snapshot = repo.get_dashboard_snapshot_extended()
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
                "currency_rates": [],
                "service_monitors": [],
                "daily_digest": None,
                "trending_topics": [],
                "custom_feeds": [],
                "favorite_ids": [],
            }
        cache.set(cache_key, snapshot, app.config["CACHE_TTL_SECONDS"])
        return jsonify(snapshot)

    @app.get("/api/items")
    def list_items():
        item_type = request.args.get("type")
        q = request.args.get("q")
        page_str = request.args.get("page")
        try:
            limit = max(1, min(200, int(request.args.get("limit", "50"))))
        except (TypeError, ValueError):
            limit = 50

        # ── Paginated mode (when ?page= is provided) ──────────
        if page_str is not None:
            try:
                page = max(1, int(page_str))
            except (TypeError, ValueError):
                page = 1
            offset = (page - 1) * limit

            cache_key = f"items:{item_type}:{q}:{limit}:p{page}"
            cached = cache.get(cache_key)
            if cached is not None:
                return jsonify(cached)

            try:
                items = repo.list_items(
                    item_type=item_type, limit=limit, q=q, offset=offset,
                )
                total = repo.count_items(item_type=item_type, q=q)
            except Exception as exc:
                logger.exception("Falha em /api/items: %s", exc)
                items, total = [], 0

            result = {
                "items": items,
                "total": total,
                "page": page,
                "per_page": limit,
            }
            cache.set(cache_key, result, app.config["CACHE_TTL_SECONDS"])
            return jsonify(result)

        # ── Legacy mode (flat array, backward-compatible) ──────
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
    @limiter.limit("10/minute")
    def add_price_watch():
        payload = request.get_json(silent=True)
        if not payload:
            return jsonify({"error": "Corpo JSON inválido"}), 400
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
    @require_admin_key
    def run_now():
        queue = get_queue(app.config)
        if queue is not None:
            from .jobs import run_daily_scrape, run_frequent_scrape

            from rq import Retry

            frequent = queue.enqueue(
                run_frequent_scrape,
                app.config["DATABASE_TARGET"],
                app.config["LOG_LEVEL"],
                job_timeout="10m",
                retry=Retry(max=3, interval=[30, 60, 120]),
                failure_ttl=86400,
            )
            daily = queue.enqueue(
                run_daily_scrape,
                app.config["DATABASE_TARGET"],
                app.config["LOG_LEVEL"],
                job_timeout="20m",
                retry=Retry(max=3, interval=[30, 60, 120]),
                failure_ttl=86400,
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
        broadcast_sse('{"type":"refresh","message":"Coleta iniciada"}')
        return jsonify({"ok": True, "message": "Coleta executada."})

    @app.post("/api/maintenance/ai-backfill")
    @limiter.limit("2/day")
    @require_admin_key
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

            from rq import Retry

            job = queue.enqueue(
                run_ai_backfill_once,
                app.config["DATABASE_TARGET"],
                app.config["LOG_LEVEL"],
                batch_size,
                max_cycles,
                job_timeout="60m",
                retry=Retry(max=2, interval=[60, 120]),
                failure_ttl=86400,
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
    @require_admin_key
    def cleanup_summaries():
        payload = repo.cleanup_duplicate_summaries()
        cache.delete("dashboard:snapshot")
        cache.delete("ai:observability")
        return jsonify({"ok": True, **payload})

    @app.post("/api/maintenance/retention")
    @limiter.limit("2/day")
    @require_admin_key
    def run_data_retention():
        retention_days = app.config.get("DATA_RETENTION_DAYS", 90)
        payload = repo.delete_old_items(retention_days)
        cache.delete("dashboard:snapshot")
        return jsonify({"ok": True, **payload})

    # ==================================================================
    # Custom Feeds CRUD
    # ==================================================================

    @app.get("/api/custom-feeds")
    def list_custom_feeds():
        return jsonify(repo.list_custom_feeds())

    @app.post("/api/custom-feeds")
    @limiter.limit("30/minute")
    def add_custom_feed():
        payload = request.get_json(silent=True)
        if not payload:
            return jsonify({"error": "Corpo JSON inválido"}), 400
        name = sanitize_text(str(payload.get("name", "")), 120)
        feed_url = str(payload.get("feed_url", "")).strip()
        if not name or not feed_url:
            return jsonify({"error": "name e feed_url são obrigatórios"}), 400
        if not is_safe_http_url(feed_url):
            return jsonify({"error": "URL inválida"}), 400
        feed_id = repo.add_custom_feed({
            "name": name,
            "feed_url": feed_url,
            "item_type": sanitize_text(str(payload.get("item_type", "news")), 30),
        })
        cache.delete("dashboard:snapshot")
        return jsonify({"ok": True, "id": feed_id}), 201

    @app.delete("/api/custom-feeds/<int:feed_id>")
    @limiter.limit("30/minute")
    def delete_custom_feed(feed_id: int):
        deleted = repo.delete_custom_feed(feed_id)
        cache.delete("dashboard:snapshot")
        return jsonify({"ok": deleted})

    @app.patch("/api/custom-feeds/<int:feed_id>/toggle")
    @limiter.limit("30/minute")
    def toggle_custom_feed(feed_id: int):
        payload = request.get_json(silent=True) or {}
        active = bool(payload.get("active", True))
        repo.toggle_custom_feed(feed_id, active)
        cache.delete("dashboard:snapshot")
        return jsonify({"ok": True})

    @app.get("/api/custom-feeds/<int:feed_id>/articles")
    @limiter.limit("10/minute")
    def feed_articles(feed_id: int):
        """Fetch and parse RSS/Atom articles for a given custom feed."""
        feeds = repo.list_custom_feeds()
        feed = next((f for f in feeds if f.get("id") == feed_id), None)
        if not feed:
            return jsonify({"error": "Feed não encontrado"}), 404

        feed_url = feed.get("feed_url", "")
        cache_key = f"rss:articles:{feed_id}"
        cached = cache.get(cache_key)
        if cached:
            return jsonify(cached)

        try:
            resp = http_requests.get(feed_url, timeout=10, headers={
                "User-Agent": "websrc-dashboard/1.0"
            })
            resp.raise_for_status()
            parsed = feedparser.parse(resp.text)
        except Exception as exc:
            logger.warning("RSS fetch failed for feed %d: %s", feed_id, exc)
            return jsonify({"error": "Falha ao buscar feed", "detail": str(exc)}), 502

        articles = []
        for entry in parsed.entries[:20]:
            published = ""
            if hasattr(entry, "published"):
                published = entry.published
            elif hasattr(entry, "updated"):
                published = entry.updated
            articles.append({
                "title": getattr(entry, "title", ""),
                "link": getattr(entry, "link", ""),
                "published": published,
                "summary": getattr(entry, "summary", "")[:200],
            })

        result = {"feed_id": feed_id, "feed_name": feed.get("name", ""), "articles": articles}
        cache.set(cache_key, result, ttl=300)  # 5 min cache
        return jsonify(result)

    # ==================================================================
    # Favorites CRUD
    # ==================================================================

    @app.get("/api/favorites")
    def list_favorites():
        return jsonify(repo.list_favorites())

    @app.post("/api/favorites")
    @limiter.limit("60/minute")
    def add_favorite():
        payload = request.get_json(silent=True)
        if not payload or "item_id" not in payload:
            return jsonify({"error": "item_id obrigatório"}), 400
        try:
            item_id = int(payload["item_id"])
        except (TypeError, ValueError):
            return jsonify({"error": "item_id inválido"}), 400
        tags = payload.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        fav_id = repo.add_favorite(item_id, tags)
        cache.delete("dashboard:snapshot")
        return jsonify({"ok": True, "id": fav_id}), 201

    @app.delete("/api/favorites/<int:item_id>")
    @limiter.limit("60/minute")
    def remove_favorite(item_id: int):
        removed = repo.remove_favorite(item_id)
        cache.delete("dashboard:snapshot")
        return jsonify({"ok": removed})

    @app.patch("/api/favorites/<int:item_id>/tags")
    @limiter.limit("60/minute")
    def update_favorite_tags(item_id: int):
        payload = request.get_json(silent=True) or {}
        tags = payload.get("tags", [])
        if not isinstance(tags, list):
            return jsonify({"error": "tags deve ser uma lista"}), 400
        repo.update_favorite_tags(item_id, tags)
        return jsonify({"ok": True})

    # ==================================================================
    # Notes CRUD
    # ==================================================================

    @app.get("/api/notes")
    def list_notes():
        item_id_str = request.args.get("item_id")
        item_id = int(item_id_str) if item_id_str else None
        return jsonify(repo.list_notes(item_id))

    @app.post("/api/notes")
    @limiter.limit("60/minute")
    def add_note():
        payload = request.get_json(silent=True)
        if not payload:
            return jsonify({"error": "Corpo JSON inválido"}), 400
        try:
            item_id = int(payload["item_id"])
        except (TypeError, ValueError, KeyError):
            return jsonify({"error": "item_id obrigatório"}), 400
        content = sanitize_text(str(payload.get("content", "")), 2000)
        if not content:
            return jsonify({"error": "content obrigatório"}), 400
        note_id = repo.add_note(item_id, content)
        return jsonify({"ok": True, "id": note_id}), 201

    @app.patch("/api/notes/<int:note_id>")
    @limiter.limit("60/minute")
    def update_note(note_id: int):
        payload = request.get_json(silent=True) or {}
        content = sanitize_text(str(payload.get("content", "")), 2000)
        if not content:
            return jsonify({"error": "content obrigatório"}), 400
        repo.update_note(note_id, content)
        return jsonify({"ok": True})

    @app.delete("/api/notes/<int:note_id>")
    @limiter.limit("60/minute")
    def delete_note(note_id: int):
        deleted = repo.delete_note(note_id)
        return jsonify({"ok": deleted})

    # ==================================================================
    # Service Monitors CRUD
    # ==================================================================

    @app.get("/api/service-monitors")
    def list_service_monitors():
        return jsonify(repo.list_service_monitors())

    @app.post("/api/service-monitors")
    @limiter.limit("20/minute")
    def add_service_monitor():
        payload = request.get_json(silent=True)
        if not payload:
            return jsonify({"error": "Corpo JSON inválido"}), 400
        name = sanitize_text(str(payload.get("name", "")), 120)
        url = str(payload.get("url", "")).strip()
        if not name or not url:
            return jsonify({"error": "name e url obrigatórios"}), 400
        if not is_safe_http_url(url):
            return jsonify({"error": "URL inválida"}), 400
        monitor_id = repo.add_service_monitor({
            "name": name,
            "url": url,
            "check_method": str(payload.get("check_method", "GET")).upper()[:6],
            "expected_status": min(599, max(100, int(payload.get("expected_status", 200)))),
            "timeout_seconds": min(30, max(1, int(payload.get("timeout_seconds", 5)))),
        })
        cache.delete("dashboard:snapshot")
        return jsonify({"ok": True, "id": monitor_id}), 201

    @app.delete("/api/service-monitors/<int:monitor_id>")
    @limiter.limit("20/minute")
    def delete_service_monitor(monitor_id: int):
        deleted = repo.delete_service_monitor(monitor_id)
        cache.delete("dashboard:snapshot")
        return jsonify({"ok": deleted})

    @app.get("/api/service-monitors/<int:monitor_id>/history")
    def service_monitor_history(monitor_id: int):
        return jsonify(repo.get_service_monitor_history(monitor_id))

    # ==================================================================
    # Currency Rates
    # ==================================================================

    @app.get("/api/currency-rates")
    def list_currency_rates():
        return jsonify(repo.list_currency_rates())

    # ==================================================================
    # Daily Digest
    # ==================================================================

    @app.get("/api/daily-digest")
    def get_daily_digest():
        digest = repo.get_latest_digest()
        return jsonify(digest or {"content": "", "highlights": []})

    # ==================================================================
    # Trending Topics
    # ==================================================================

    @app.get("/api/trending")
    def get_trending():
        cache_key = "trending:topics"
        cached = cache.get(cache_key)
        if cached is not None:
            return jsonify(cached)
        topics = repo.get_trending_topics()
        cache.set(cache_key, topics, 300)
        return jsonify(topics)

    # ==================================================================
    # Saved Filters
    # ==================================================================

    @app.get("/api/saved-filters")
    def list_saved_filters():
        return jsonify(repo.list_saved_filters())

    @app.post("/api/saved-filters")
    @limiter.limit("30/minute")
    def add_saved_filter():
        payload = request.get_json(silent=True)
        if not payload:
            return jsonify({"error": "Corpo JSON inválido"}), 400
        name = sanitize_text(str(payload.get("name", "")), 80)
        if not name:
            return jsonify({"error": "name obrigatório"}), 400
        filter_data = payload.get("filter", {})
        filter_id = repo.add_saved_filter(name, filter_data)
        return jsonify({"ok": True, "id": filter_id}), 201

    @app.delete("/api/saved-filters/<int:filter_id>")
    @limiter.limit("30/minute")
    def delete_saved_filter(filter_id: int):
        deleted = repo.delete_saved_filter(filter_id)
        return jsonify({"ok": deleted})

    # ==================================================================
    # Web Push Subscriptions
    # ==================================================================

    @app.get("/api/push/vapid-public-key")
    def vapid_public_key():
        key = app.config.get("VAPID_PUBLIC_KEY", "")
        return jsonify({"publicKey": key})

    @app.post("/api/push/subscribe")
    @limiter.limit("5/minute")
    def push_subscribe():
        payload = request.get_json(silent=True)
        if not payload or "endpoint" not in payload:
            return jsonify({"error": "endpoint obrigatório"}), 400
        endpoint = str(payload["endpoint"])
        keys = payload.get("keys", {})
        from .utils import json_dumps as _jd
        sub_id = repo.add_push_subscription(endpoint, _jd(keys))
        return jsonify({"ok": True, "id": sub_id}), 201

    @app.post("/api/push/unsubscribe")
    @limiter.limit("10/minute")
    def push_unsubscribe():
        payload = request.get_json(silent=True)
        if not payload or "endpoint" not in payload:
            return jsonify({"error": "endpoint obrigatório"}), 400
        removed = repo.remove_push_subscription(str(payload["endpoint"]))
        return jsonify({"ok": removed})

    # ==================================================================
    # Price Watch DELETE/PATCH (previously pending)
    # ==================================================================

    @app.delete("/api/price-watch/<int:watch_id>")
    @limiter.limit("20/minute")
    def delete_price_watch(watch_id: int):
        with get_connection(app.config["DATABASE_TARGET"]) as conn:
            if repo.is_postgres:
                conn.execute(
                    "DELETE FROM price_history"
                    " WHERE watch_id = %s",
                    (watch_id,),
                )
                rows2 = conn.execute(
                    "DELETE FROM price_watches"
                    " WHERE id = %s RETURNING id",
                    (watch_id,),
                ).fetchall()
                conn.commit()
                deleted = len(rows2) > 0
            else:
                conn.execute(
                    "DELETE FROM price_history"
                    " WHERE watch_id = ?",
                    (watch_id,),
                )
                cursor = conn.execute(
                    "DELETE FROM price_watches"
                    " WHERE id = ?",
                    (watch_id,),
                )
                conn.commit()
                deleted = (cursor.rowcount or 0) > 0
        cache.delete("dashboard:snapshot")
        return jsonify({"ok": deleted})

    @app.patch("/api/price-watch/<int:watch_id>")
    @limiter.limit("20/minute")
    def update_price_watch(watch_id: int):
        payload = request.get_json(silent=True) or {}
        updates = []
        params = []
        if "name" in payload:
            updates.append("name = %s" if repo.is_postgres else "name = ?")
            params.append(sanitize_text(str(payload["name"]), 120))
        if "target_price" in payload:
            try:
                tp = float(payload["target_price"])
                updates.append("target_price = %s" if repo.is_postgres else "target_price = ?")
                params.append(tp)
            except (TypeError, ValueError):
                return jsonify({"error": "target_price inválido"}), 400
        if "active" in payload:
            val = payload["active"]
            updates.append("active = %s" if repo.is_postgres else "active = ?")
            params.append(val if repo.is_postgres else (1 if val else 0))
        if not updates:
            return jsonify({"error": "Nenhum campo para atualizar"}), 400
        params.append(watch_id)
        placeholder = "%s" if repo.is_postgres else "?"
        sql = f"UPDATE price_watches SET {', '.join(updates)} WHERE id = {placeholder}"
        with get_connection(app.config["DATABASE_TARGET"]) as conn:
            conn.execute(sql, tuple(params))
            conn.commit()
        cache.delete("dashboard:snapshot")
        return jsonify({"ok": True})

    # ==================================================================
    # PDF Export
    # ==================================================================

    @app.get("/api/export/pdf")
    @limiter.limit("3/hour")
    def export_pdf():
        try:
            snapshot = repo.get_dashboard_snapshot_extended()
            lines = [f"# Dashboard Report - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"]
            for section in ["news", "tech_ai", "jobs", "promotions", "videos"]:
                items = snapshot.get(section, [])
                if items:
                    lines.append(f"\n## {section.replace('_', ' ').title()} ({len(items)} items)\n")
                    for item in items[:20]:
                        lines.append(f"- {item.get('title', 'N/A')}")
                        if item.get("url"):
                            lines.append(f"  URL: {item['url']}")
            report = "\n".join(lines)
            return app.response_class(
                report,
                mimetype="text/markdown",
                headers={"Content-Disposition": "attachment; filename=dashboard-report.md"},
            )
        except Exception as exc:
            logger.exception("Falha no export: %s", exc)
            return jsonify({"error": "Falha ao gerar relatório"}), 500

    # ==================================================================
    # OpenAPI spec
    # ==================================================================

    @app.get("/api/openapi.json")
    @limiter.exempt
    def openapi_spec():
        spec = {
            "openapi": "3.0.3",
            "info": {
                "title": "Personal Dashboard API",
                "version": "2.0.0",
                "description": "API do Dashboard Pessoal da Internet",
            },
            "paths": {
                "/api/dashboard": {"get": {"summary": "Dashboard snapshot", "tags": ["Dashboard"]}},
                "/api/items": {"get": {"summary": "List items with filters", "tags": ["Items"]}},
                "/api/ai-observability": {"get": {"summary": "AI observability metrics", "tags": ["AI"]}},
                "/api/price-watch": {
                    "post": {"summary": "Add price watch", "tags": ["Prices"]},
                },
                "/api/price-watch/{id}": {
                    "delete": {"summary": "Delete price watch", "tags": ["Prices"]},
                    "patch": {"summary": "Update price watch", "tags": ["Prices"]},
                },
                "/api/price-history/{id}": {"get": {"summary": "Price history", "tags": ["Prices"]}},
                "/api/custom-feeds": {
                    "get": {"summary": "List custom feeds", "tags": ["Feeds"]},
                    "post": {"summary": "Add custom feed", "tags": ["Feeds"]},
                },
                "/api/custom-feeds/{id}": {"delete": {"summary": "Delete feed", "tags": ["Feeds"]}},
                "/api/favorites": {
                    "get": {"summary": "List favorites", "tags": ["Favorites"]},
                    "post": {"summary": "Add favorite", "tags": ["Favorites"]},
                },
                "/api/favorites/{item_id}": {"delete": {"summary": "Remove favorite", "tags": ["Favorites"]}},
                "/api/notes": {
                    "get": {"summary": "List notes", "tags": ["Notes"]},
                    "post": {"summary": "Add note", "tags": ["Notes"]},
                },
                "/api/notes/{id}": {
                    "patch": {"summary": "Update note", "tags": ["Notes"]},
                    "delete": {"summary": "Delete note", "tags": ["Notes"]},
                },
                "/api/service-monitors": {
                    "get": {"summary": "List service monitors", "tags": ["Monitors"]},
                    "post": {"summary": "Add monitor", "tags": ["Monitors"]},
                },
                "/api/service-monitors/{id}": {"delete": {"summary": "Delete monitor", "tags": ["Monitors"]}},
                "/api/service-monitors/{id}/history": {"get": {"summary": "Monitor history", "tags": ["Monitors"]}},
                "/api/currency-rates": {"get": {"summary": "Currency exchange rates", "tags": ["Currency"]}},
                "/api/daily-digest": {"get": {"summary": "Latest AI daily digest", "tags": ["Digest"]}},
                "/api/trending": {"get": {"summary": "Trending topics", "tags": ["Trending"]}},
                "/api/saved-filters": {
                    "get": {"summary": "List saved filters", "tags": ["Filters"]},
                    "post": {"summary": "Save filter", "tags": ["Filters"]},
                },
                "/api/saved-filters/{id}": {"delete": {"summary": "Delete filter", "tags": ["Filters"]}},
                "/api/push/subscribe": {"post": {"summary": "Subscribe to push", "tags": ["Push"]}},
                "/api/push/unsubscribe": {"post": {"summary": "Unsubscribe push", "tags": ["Push"]}},
                "/api/export/pdf": {"get": {"summary": "Export dashboard as markdown", "tags": ["Export"]}},
                "/api/llm-status": {"get": {"summary": "LLM health probe", "tags": ["AI"]}},
                "/api/smart-alerts/analyze": {"post": {"summary": "AI smart alert analysis", "tags": ["AI"]}},
                "/api/custom-feeds/{id}/articles": {"get": {"summary": "Fetch RSS articles", "tags": ["Feeds"]}},
                "/api/stream": {"get": {"summary": "SSE real-time stream", "tags": ["System"]}},
                "/health": {"get": {"summary": "Health check", "tags": ["System"]}},
                "/metrics": {"get": {"summary": "Prometheus metrics", "tags": ["System"]}},
            },
        }
        return jsonify(spec)

    @app.get("/docs")
    @limiter.exempt
    def swagger_ui():
        return """<!DOCTYPE html>
<html><head><title>API Docs</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
</head><body>
<div id="swagger-ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>SwaggerUIBundle({url:"/api/openapi.json",dom_id:"#swagger-ui"})</script>
</body></html>"""
