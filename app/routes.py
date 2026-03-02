import logging
import time
import queue as _queue
import json as _json
import secrets
from datetime import datetime, timezone, timedelta

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

    # ── In-memory log buffer for log viewer ──────────────
    import collections

    class _BufferHandler(logging.Handler):
        def __init__(self, buffer, maxlen=500):
            super().__init__()
            self.buffer = buffer
        def emit(self, record):
            try:
                self.buffer.append({
                    "level": record.levelname,
                    "message": self.format(record),
                    "logger": record.name,
                    "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
                })
            except Exception:
                pass

    log_buffer: collections.deque = collections.deque(maxlen=500)
    app._log_buffer = log_buffer  # type: ignore[attr-defined]
    buf_handler = _BufferHandler(log_buffer)
    buf_handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger().addHandler(buf_handler)

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
            # Notification center
            repo.add_notification(
                title=alert.get("title", ""),
                message=alert.get("message", ""),
                notif_type=alert.get("type", "info"),
            )

        # Fire webhooks
        if alerts:
            try:
                fire_wh = getattr(app, "fire_webhooks", None)
                if fire_wh:
                    fire_wh("alert", {"alerts": alerts})
            except Exception:
                pass

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
    # App Settings (Settings Panel)
    # ==================================================================

    # Keys that can be changed via the settings panel
    SETTINGS_SCHEMA: dict = {
        # ── Geral ──
        "scrape_interval_minutes": {"type": "int", "min": 1, "max": 1440, "default": "30"},
        "daily_interval_hours": {"type": "int", "min": 1, "max": 168, "default": "24"},
        "feed_entry_limit": {"type": "int", "min": 5, "max": 200, "default": "30"},
        "data_retention_days": {"type": "int", "min": 7, "max": 3650, "default": "90"},
        "cache_ttl_seconds": {"type": "int", "min": 10, "max": 3600, "default": "90"},
        # ── Clima ──
        "weather_city": {"type": "str", "max_len": 100, "default": "Lajeado"},
        "weather_state": {"type": "str", "max_len": 100, "default": "Rio Grande do Sul"},
        "weather_country_code": {"type": "str", "max_len": 5, "default": "BR"},
        "weather_lat": {"type": "float", "min": -90, "max": 90, "default": "-29.4669"},
        "weather_lon": {"type": "float", "min": -180, "max": 180, "default": "-51.9614"},
        # ── IA Local ──
        "ai_local_enabled": {"type": "bool", "default": "0"},
        "ai_local_backend": {"type": "str", "choices": ["ollama", "llama_cpp"], "default": "llama_cpp"},
        "ai_local_url": {"type": "url", "max_len": 300, "default": "http://llamacpp:8080"},
        "ai_local_model": {"type": "str", "max_len": 200, "default": "qwen2.5:7b-instruct"},
        "ai_local_timeout_seconds": {"type": "int", "min": 5, "max": 300, "default": "30"},
        "ai_local_retries": {"type": "int", "min": 0, "max": 10, "default": "2"},
        "ai_local_max_enrich_per_run": {"type": "int", "min": 0, "max": 100, "default": "12"},
        # ── Moedas ──
        "currency_api_url": {"type": "url", "max_len": 500, "default": "https://economia.awesomeapi.com.br/last/USD-BRL,EUR-BRL,BTC-BRL"},
        "currency_update_minutes": {"type": "int", "min": 1, "max": 1440, "default": "15"},
        # ── Monitor de Serviços ──
        "service_monitor_interval_minutes": {"type": "int", "min": 1, "max": 1440, "default": "5"},
        # ── Email Digest ──
        "smtp_host": {"type": "str", "max_len": 300, "default": ""},
        "smtp_port": {"type": "int", "min": 1, "max": 65535, "default": "587"},
        "smtp_user": {"type": "str", "max_len": 200, "default": ""},
        "smtp_from": {"type": "str", "max_len": 200, "default": ""},
        "email_digest_recipients": {"type": "str", "max_len": 500, "default": ""},
        # ── Fontes (JSON arrays) ──
        "news_feeds_custom": {"type": "json", "default": "[]"},
        "youtube_feeds_custom": {"type": "json", "default": "[]"},
        "github_repos_custom": {"type": "json", "default": "[]"},
        "job_feeds_custom": {"type": "json", "default": "[]"},
        # ── Visibilidade dos cards ──
        "card_weather": {"type": "bool", "default": "1"},
        "card_alerts": {"type": "bool", "default": "1"},
        "card_prices": {"type": "bool", "default": "1"},
        "card_news": {"type": "bool", "default": "1"},
        "card_promotions": {"type": "bool", "default": "1"},
        "card_videos": {"type": "bool", "default": "1"},
        "card_jobs": {"type": "bool", "default": "1"},
        "card_tech": {"type": "bool", "default": "1"},
        "card_ai_observability": {"type": "bool", "default": "1"},
        "card_releases": {"type": "bool", "default": "1"},
        "card_currency": {"type": "bool", "default": "1"},
        "card_service_monitor": {"type": "bool", "default": "1"},
        "card_daily_digest": {"type": "bool", "default": "1"},
        "card_trending": {"type": "bool", "default": "1"},
        "card_custom_feeds": {"type": "bool", "default": "1"},
        "card_favorites": {"type": "bool", "default": "1"},
        "card_release_calendar": {"type": "bool", "default": "1"},
        "card_system_uptime": {"type": "bool", "default": "1"},
        "card_cache_analytics": {"type": "bool", "default": "1"},
        "card_workers": {"type": "bool", "default": "1"},
        "card_ai_chat": {"type": "bool", "default": "1"},
        "card_events_calendar": {"type": "bool", "default": "1"},
        "card_webhooks": {"type": "bool", "default": "1"},
        "show_status_bar": {"type": "bool", "default": "1"},
    }

    def _validate_setting(key: str, value: str) -> tuple[bool, str]:
        schema = SETTINGS_SCHEMA.get(key)
        if not schema:
            return False, f"Unknown setting: {key}"
        stype = schema["type"]
        if stype == "int":
            try:
                v = int(value)
                if v < schema.get("min", -9999999) or v > schema.get("max", 9999999):
                    return False, f"{key}: valor fora do intervalo"
            except ValueError:
                return False, f"{key}: deve ser número inteiro"
        elif stype == "float":
            try:
                v = float(value)
                if v < schema.get("min", -9999999) or v > schema.get("max", 9999999):
                    return False, f"{key}: valor fora do intervalo"
            except ValueError:
                return False, f"{key}: deve ser número"
        elif stype == "bool":
            if value not in ("0", "1"):
                return False, f"{key}: deve ser 0 ou 1"
        elif stype == "str":
            if len(value) > schema.get("max_len", 500):
                return False, f"{key}: texto muito longo"
            if "choices" in schema and value and value not in schema["choices"]:
                return False, f"{key}: valor inválido"
        elif stype == "url":
            if value and len(value) > schema.get("max_len", 500):
                return False, f"{key}: URL muito longa"
        elif stype == "json":
            try:
                _json.loads(value)
            except _json.JSONDecodeError:
                return False, f"{key}: JSON inválido"
        return True, ""

    @app.get("/api/settings")
    @limiter.limit("30/minute")
    def get_settings():
        db_settings = repo.get_all_settings()
        # Merge defaults with stored values
        result = {}
        for key, schema in SETTINGS_SCHEMA.items():
            config_key = key.upper()
            env_val = str(app.config.get(config_key, schema["default"]))
            result[key] = db_settings.get(key, env_val)
        return jsonify(result)

    @app.put("/api/settings")
    @limiter.limit("10/minute")
    def update_settings():
        body = request.get_json(silent=True) or {}
        errors = []
        valid = {}
        for key, value in body.items():
            if key not in SETTINGS_SCHEMA:
                continue
            ok, msg = _validate_setting(key, str(value))
            if ok:
                valid[key] = str(value)
            else:
                errors.append(msg)
        if errors:
            return jsonify({"error": "; ".join(errors)}), 400
        if not valid:
            return jsonify({"error": "Nenhuma configuração válida enviada"}), 400
        repo.set_settings_bulk(valid)

        # Reload config values into app.config for immediate effect
        for key, value in valid.items():
            config_key = key.upper()
            schema = SETTINGS_SCHEMA[key]
            if schema["type"] == "int":
                app.config[config_key] = int(value)
            elif schema["type"] == "float":
                app.config[config_key] = float(value)
            elif schema["type"] == "bool":
                app.config[config_key] = value == "1"
            else:
                app.config[config_key] = value

        return jsonify({"updated": list(valid.keys()), "count": len(valid)})

    @app.get("/api/settings/schema")
    @limiter.limit("30/minute")
    def get_settings_schema():
        return jsonify(SETTINGS_SCHEMA)

    # ==================================================================
    # System Uptime / Health-check Dashboard (#1)
    # ==================================================================

    _boot_time = time.time()

    @app.get("/api/system/uptime")
    @limiter.limit("30/minute")
    def system_uptime():
        """Return uptime of each service component."""
        uptime_s = time.time() - _boot_time
        checks = {}

        # API uptime
        checks["api"] = {"status": "ok", "uptime_seconds": round(uptime_s, 1)}

        # Postgres
        try:
            with get_connection(app.config["DATABASE_TARGET"]) as conn:
                conn.execute("SELECT 1")
            checks["postgres"] = {"status": "ok"}
        except Exception as exc:
            checks["postgres"] = {"status": "error", "detail": str(exc)[:100]}

        # Redis
        if app.config.get("QUEUE_ENABLED"):
            try:
                import redis as _redis
                r = _redis.from_url(app.config["REDIS_URL"])
                info = r.info("server")
                checks["redis"] = {
                    "status": "ok",
                    "uptime_seconds": info.get("uptime_in_seconds", 0),
                }
            except Exception as exc:
                checks["redis"] = {"status": "error", "detail": str(exc)[:100]}

        # LLM
        if app.config.get("AI_LOCAL_ENABLED"):
            try:
                import urllib.request
                url = app.config["AI_LOCAL_URL"].rstrip("/") + "/health"
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    checks["llm"] = {"status": "ok" if resp.status == 200 else "degraded"}
            except Exception as exc:
                checks["llm"] = {"status": "error", "detail": str(exc)[:100]}

        # RQ Workers
        if app.config.get("QUEUE_ENABLED"):
            try:
                import redis as _redis
                from rq import Worker
                r = _redis.from_url(app.config["REDIS_URL"])
                workers = Worker.all(connection=r)
                checks["workers"] = {
                    "status": "ok",
                    "count": len(workers),
                    "names": [w.name for w in workers[:10]],
                }
            except Exception:
                checks["workers"] = {"status": "unknown"}

        return jsonify({"boot_time": _boot_time, "uptime_seconds": round(uptime_s, 1), "services": checks})

    # ==================================================================
    # Log Viewer (#2)
    # ==================================================================

    @app.get("/api/logs")
    @limiter.limit("10/minute")
    @require_admin_key
    def get_logs():
        """Return recent application log entries."""
        import collections
        level_filter = request.args.get("level", "").upper()
        limit = min(500, max(10, int(request.args.get("limit", "100"))))

        # Read from in-memory log buffer (attached on startup)
        entries = list(getattr(app, '_log_buffer', collections.deque()))
        if level_filter:
            entries = [e for e in entries if e.get("level", "").upper() == level_filter]
        entries = entries[-limit:]
        return jsonify({"entries": entries, "total": len(entries)})

    # ==================================================================
    # RQ Workers Info (#3)
    # ==================================================================

    @app.get("/api/workers")
    @limiter.limit("10/minute")
    def workers_info():
        """Return info about RQ workers."""
        if not app.config.get("QUEUE_ENABLED"):
            return jsonify({"workers": [], "message": "Queue not enabled"})
        try:
            import redis as _redis
            from rq import Worker, Queue as RQQueue
            r = _redis.from_url(app.config["REDIS_URL"])
            workers = Worker.all(connection=r)
            q = RQQueue(connection=r)
            return jsonify({
                "workers": [
                    {
                        "name": w.name,
                        "state": w.get_state(),
                        "current_job": str(w.get_current_job()) if w.get_current_job() else None,
                        "successful_job_count": w.successful_job_count,
                        "failed_job_count": w.failed_job_count,
                    }
                    for w in workers
                ],
                "queue_length": q.count,
                "failed_count": q.failed_job_registry.count if hasattr(q, "failed_job_registry") else 0,
            })
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    # ==================================================================
    # Cache Analytics (#4)
    # ==================================================================

    @app.get("/api/cache/stats")
    @limiter.limit("10/minute")
    def cache_stats():
        """Return cache statistics."""
        stats = cache.get_stats() if hasattr(cache, "get_stats") else {}
        # Try Redis INFO if available
        if app.config.get("QUEUE_ENABLED"):
            try:
                import redis as _redis
                r = _redis.from_url(app.config["REDIS_URL"])
                info = r.info("stats")
                memory = r.info("memory")
                stats["redis_hits"] = info.get("keyspace_hits", 0)
                stats["redis_misses"] = info.get("keyspace_misses", 0)
                total = stats["redis_hits"] + stats["redis_misses"]
                stats["hit_rate_pct"] = round(stats["redis_hits"] / max(total, 1) * 100, 1)
                stats["used_memory_human"] = memory.get("used_memory_human", "?")
                stats["total_keys"] = r.dbsize()
            except Exception as exc:
                stats["redis_error"] = str(exc)[:100]
        return jsonify(stats)

    # ==================================================================
    # Shareable Dashboard (#5)
    # ==================================================================

    @app.post("/api/share")
    @limiter.limit("5/minute")
    def create_share():
        """Generate a shareable read-only dashboard link."""
        payload = request.get_json(silent=True) or {}
        label = sanitize_text(str(payload.get("label", "Dashboard share")), 120)
        hours = min(720, max(1, int(payload.get("hours", app.config.get("SHARE_LINK_EXPIRY_HOURS", 72)))))
        token = secrets.token_urlsafe(24)
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
        share_id = repo.create_shared_dashboard(token, label, expires_at)
        return jsonify({"ok": True, "id": share_id, "token": token, "expires_at": expires_at}), 201

    @app.get("/api/shares")
    @limiter.limit("10/minute")
    def list_shares():
        return jsonify(repo.list_shared_dashboards())

    @app.delete("/api/shares/<int:share_id>")
    @limiter.limit("10/minute")
    def delete_share(share_id: int):
        return jsonify({"ok": repo.delete_shared_dashboard(share_id)})

    @app.get("/shared/<token>")
    @limiter.limit("30/minute")
    def shared_dashboard(token: str):
        """Serve read-only shared dashboard."""
        share = repo.get_shared_dashboard(token)
        if not share:
            return jsonify({"error": "Link inválido ou expirado"}), 404
        expires_at = share.get("expires_at", "")
        try:
            exp_dt = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if exp_dt < datetime.now(timezone.utc):
                return jsonify({"error": "Link expirado"}), 410
        except Exception:
            pass
        return render_template("index.html")

    @app.get("/api/shared/<token>/dashboard")
    @limiter.limit("30/minute")
    def shared_dashboard_data(token: str):
        """Return dashboard data for shared link (read-only)."""
        share = repo.get_shared_dashboard(token)
        if not share:
            return jsonify({"error": "Link inválido"}), 404
        expires_at = share.get("expires_at", "")
        try:
            exp_dt = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if exp_dt < datetime.now(timezone.utc):
                return jsonify({"error": "Link expirado"}), 410
        except Exception:
            pass
        try:
            snapshot = repo.get_dashboard_snapshot_extended()
        except Exception:
            snapshot = {}
        return jsonify(snapshot)

    # ==================================================================
    # Notifications Center (#7)
    # ==================================================================

    @app.get("/api/notifications")
    @limiter.limit("30/minute")
    def list_notifications():
        limit = min(200, max(1, int(request.args.get("limit", "50"))))
        return jsonify(repo.list_notifications(limit))

    @app.get("/api/notifications/unread-count")
    @limiter.limit("60/minute")
    def unread_notification_count():
        return jsonify({"count": repo.count_unread_notifications()})

    @app.patch("/api/notifications/<int:notif_id>/read")
    @limiter.limit("60/minute")
    def mark_notification_read(notif_id: int):
        return jsonify({"ok": repo.mark_notification_read(notif_id)})

    @app.post("/api/notifications/mark-all-read")
    @limiter.limit("10/minute")
    def mark_all_notifications_read():
        count = repo.mark_all_notifications_read()
        return jsonify({"ok": True, "count": count})

    # ==================================================================
    # AI Chat About Data (#12)
    # ==================================================================

    @app.post("/api/ai-chat")
    @limiter.limit("6/minute")
    def ai_chat():
        """Chat with AI about dashboard data."""
        if not app.config.get("AI_LOCAL_ENABLED"):
            return jsonify({"error": "IA local não habilitada"}), 503

        payload = request.get_json(silent=True)
        if not payload or not payload.get("message"):
            return jsonify({"error": "message obrigatório"}), 400

        user_msg = sanitize_text(str(payload["message"]), 500)

        # Build context from dashboard
        try:
            snapshot = cache.get("dashboard:snapshot") or repo.get_dashboard_snapshot()
        except Exception:
            snapshot = {}

        context_parts = []
        for section in ["news", "tech_ai", "jobs", "promotions"]:
            items = snapshot.get(section, [])[:5]
            if items:
                titles = [it.get("title", "") for it in items]
                context_parts.append(f"{section}: {'; '.join(titles)}")

        prices = snapshot.get("prices", [])[:5]
        if prices:
            price_info = [f"{p.get('name', '')}: R${p.get('last_price', '?')}" for p in prices]
            context_parts.append(f"preços: {'; '.join(price_info)}")

        system_prompt = (
            "Você é um assistente sobre dados do dashboard pessoal do usuário. "
            "Responda em português de forma concisa. Dados atuais:\n"
            + "\n".join(context_parts)
        )

        try:
            ai_url = app.config["AI_LOCAL_URL"].rstrip("/")
            endpoint = app.config.get("AI_LOCAL_LLAMA_CPP_CHAT_ENDPOINT", "/v1/chat/completions")
            resp = http_requests.post(
                f"{ai_url}{endpoint}",
                json={
                    "model": app.config.get("AI_LOCAL_MODEL", "qwen2.5:7b-instruct"),
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_msg},
                    ],
                    "max_tokens": 300,
                    "temperature": 0.7,
                },
                timeout=app.config.get("AI_LOCAL_TIMEOUT_SECONDS", 30),
            )
            resp.raise_for_status()
            data = resp.json()
            reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return jsonify({"reply": reply.strip()})
        except Exception as exc:
            logger.warning("AI chat error: %s", exc)
            return jsonify({"error": "Falha na IA", "detail": str(exc)[:200]}), 502

    # ==================================================================
    # Sentiment Detection (#13) - enrichment hook
    # ==================================================================

    @app.get("/api/items/<int:item_id>/sentiment")
    @limiter.limit("20/minute")
    def get_item_sentiment(item_id: int):
        """Get or compute sentiment for an item."""
        from .utils import json_loads as _jl
        with get_connection(app.config["DATABASE_TARGET"]) as conn:
            row = conn.execute(
                repo._sql("SELECT extra_json, title, summary FROM items WHERE id = ?"),
                (item_id,),
            ).fetchone()
        if not row:
            return jsonify({"error": "Item não encontrado"}), 404
        row = dict(row)
        extra = _jl(row.get("extra_json")) or {}
        if "sentiment" in extra:
            return jsonify({"sentiment": extra["sentiment"]})

        # Quick keyword-based sentiment
        text = f"{row.get('title', '')} {row.get('summary', '')}".lower()
        positive = sum(1 for w in ["bom", "ótimo", "excelente", "alta", "subiu", "growth", "good", "great", "success", "up", "novo", "lança"] if w in text)
        negative = sum(1 for w in ["ruim", "queda", "crise", "erro", "falha", "bad", "down", "crash", "hack", "vulnerab", "ataque", "guerra"] if w in text)

        if positive > negative:
            sentiment = "positive"
        elif negative > positive:
            sentiment = "negative"
        else:
            sentiment = "neutral"

        # Persist
        extra["sentiment"] = sentiment
        from .utils import json_dumps as _jd
        with get_connection(app.config["DATABASE_TARGET"]) as conn:
            conn.execute(
                repo._sql("UPDATE items SET extra_json = ? WHERE id = ?"),
                (_jd(extra), item_id),
            )
            conn.commit()

        return jsonify({"sentiment": sentiment})

    # ==================================================================
    # Price Trend Forecast (#14)
    # ==================================================================

    @app.get("/api/price-forecast/<int:watch_id>")
    @limiter.limit("10/minute")
    def price_forecast(watch_id: int):
        """Simple linear regression forecast for price history."""
        history = repo.get_price_history(watch_id)
        if len(history) < 3:
            return jsonify({"error": "Dados insuficientes (mínimo 3 pontos)"}), 400

        # Simple linear regression
        prices = [float(h["price"]) for h in history]
        n = len(prices)
        x = list(range(n))
        x_mean = sum(x) / n
        y_mean = sum(prices) / n

        numerator = sum((x[i] - x_mean) * (prices[i] - y_mean) for i in range(n))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            slope = 0.0
            intercept = y_mean
        else:
            slope = numerator / denominator
            intercept = y_mean - slope * x_mean

        # Forecast next 7 points
        forecast = []
        for i in range(1, 8):
            val = intercept + slope * (n - 1 + i)
            forecast.append(round(max(0, val), 2))

        trend = "up" if slope > 0.01 else ("down" if slope < -0.01 else "stable")

        return jsonify({
            "watch_id": watch_id,
            "trend": trend,
            "slope": round(slope, 4),
            "forecast_7d": forecast,
            "current_price": prices[-1] if prices else None,
            "data_points": n,
        })

    # ==================================================================
    # Tags in price watch (#15)
    # ==================================================================

    @app.patch("/api/price-watch/<int:watch_id>/tags")
    @limiter.limit("20/minute")
    def update_price_watch_tags(watch_id: int):
        payload = request.get_json(silent=True) or {}
        tags = payload.get("tags", [])
        if not isinstance(tags, list):
            return jsonify({"error": "tags deve ser uma lista"}), 400
        from .utils import json_dumps as _jd
        with get_connection(app.config["DATABASE_TARGET"]) as conn:
            conn.execute(
                repo._sql("UPDATE price_watches SET tags = ? WHERE id = ?"),
                (_jd(tags), watch_id),
            )
            conn.commit()
        cache.delete("dashboard:snapshot")
        return jsonify({"ok": True})

    # ==================================================================
    # Webhooks CRUD (#16)
    # ==================================================================

    @app.get("/api/webhooks")
    @limiter.limit("15/minute")
    def list_webhooks():
        return jsonify(repo.list_webhooks())

    @app.post("/api/webhooks")
    @limiter.limit("10/minute")
    def add_webhook():
        payload = request.get_json(silent=True)
        if not payload:
            return jsonify({"error": "Corpo JSON inválido"}), 400
        name = sanitize_text(str(payload.get("name", "")), 120)
        url = str(payload.get("url", "")).strip()
        if not name or not url:
            return jsonify({"error": "name e url obrigatórios"}), 400
        if not is_safe_http_url(url):
            return jsonify({"error": "URL inválida"}), 400
        event_types = payload.get("event_types", ["alert"])
        if not isinstance(event_types, list):
            event_types = ["alert"]
        wh_id = repo.add_webhook({
            "name": name,
            "url": url,
            "event_types": event_types,
            "secret": payload.get("secret"),
            "active": payload.get("active", True),
        })
        return jsonify({"ok": True, "id": wh_id}), 201

    @app.delete("/api/webhooks/<int:wh_id>")
    @limiter.limit("10/minute")
    def delete_webhook(wh_id: int):
        return jsonify({"ok": repo.delete_webhook(wh_id)})

    def fire_webhooks(event_type: str, payload: dict) -> None:
        """Fire outbound webhooks for a given event type (non-blocking best-effort)."""
        import threading

        def _send(hook, data):
            try:
                headers = {"Content-Type": "application/json", "X-Webhook-Event": event_type}
                if hook.get("secret"):
                    import hashlib, hmac
                    body = _json.dumps(data)
                    sig = hmac.new(hook["secret"].encode(), body.encode(), hashlib.sha256).hexdigest()
                    headers["X-Webhook-Signature"] = sig
                http_requests.post(
                    hook["url"],
                    json=data,
                    headers=headers,
                    timeout=app.config.get("WEBHOOK_TIMEOUT_SECONDS", 10),
                )
            except Exception as exc:
                logger.warning("Webhook %s failed: %s", hook.get("name"), exc)

        hooks = repo.get_active_webhooks(event_type)
        for hook in hooks:
            threading.Thread(target=_send, args=(hook, payload), daemon=True).start()

    # Attach to app for use elsewhere
    app.fire_webhooks = fire_webhooks  # type: ignore[attr-defined]

    # ==================================================================
    # Email Digest (#11)
    # ==================================================================

    @app.post("/api/email-digest/send")
    @limiter.limit("2/hour")
    @require_admin_key
    def send_email_digest():
        """Send current daily digest via email."""
        smtp_host = app.config.get("SMTP_HOST", "")
        if not smtp_host:
            return jsonify({"error": "SMTP não configurado"}), 503

        recipients = [r.strip() for r in app.config.get("EMAIL_DIGEST_RECIPIENTS", "").split(",") if r.strip()]
        if not recipients:
            return jsonify({"error": "Nenhum destinatário configurado"}), 400

        digest = repo.get_latest_digest()
        if not digest:
            return jsonify({"error": "Nenhum digest disponível"}), 404

        subject = f"Dashboard Digest - {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        body = digest.get("content", "Sem conteúdo")

        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart

            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = app.config.get("SMTP_FROM", app.config.get("SMTP_USER", ""))
            msg["To"] = ", ".join(recipients)
            msg.attach(MIMEText(body, "plain", "utf-8"))

            port = int(app.config.get("SMTP_PORT", 587))
            use_tls = app.config.get("SMTP_USE_TLS", True)

            with smtplib.SMTP(smtp_host, port) as server:
                if use_tls:
                    server.starttls()
                user = app.config.get("SMTP_USER", "")
                pwd = app.config.get("SMTP_PASSWORD", "")
                if user and pwd:
                    server.login(user, pwd)
                server.sendmail(msg["From"], recipients, msg.as_string())

            return jsonify({"ok": True, "recipients": len(recipients)})
        except Exception as exc:
            logger.exception("Email digest error: %s", exc)
            return jsonify({"error": str(exc)[:200]}), 500

    # ==================================================================
    # Layout Presets (#6)
    # ==================================================================

    @app.get("/api/layout-presets")
    @limiter.limit("15/minute")
    def get_layout_presets():
        """Return built-in and saved layout presets."""
        presets = [
            {"id": "default", "name": "Padrão", "builtin": True},
            {"id": "compact", "name": "Compacto", "builtin": True},
            {"id": "analytics", "name": "Analytics", "builtin": True},
            {"id": "minimal", "name": "Minimal", "builtin": True},
        ]
        return jsonify(presets)

    # ==================================================================
    # Events Calendar (#10)
    # ==================================================================

    @app.get("/api/events-calendar")
    @limiter.limit("15/minute")
    def events_calendar():
        """Aggregate events from alerts, backups, digests for a calendar view."""
        events = []

        # Alerts as events
        alerts = repo.list_alerts(limit=30)
        for a in alerts:
            events.append({
                "type": "alert",
                "title": a.get("title", "Alerta"),
                "date": a.get("created_at", ""),
                "color": "#ef4444",
            })

        # Digests
        with get_connection(app.config["DATABASE_TARGET"]) as conn:
            rows = conn.execute(
                "SELECT digest_date, content FROM daily_digests ORDER BY digest_date DESC LIMIT 30",
            ).fetchall()
            for r in rows:
                row = dict(r)
                events.append({
                    "type": "digest",
                    "title": "Resumo Diário",
                    "date": row.get("digest_date", ""),
                    "color": "#3b82f6",
                })

        # Service monitor failures
        monitors = repo.list_service_monitors()
        for m in monitors:
            if m.get("last_status") == "down":
                events.append({
                    "type": "monitor_down",
                    "title": f"⚠ {m.get('name', '')} offline",
                    "date": m.get("last_checked_at", ""),
                    "color": "#f59e0b",
                })

        events.sort(key=lambda e: e.get("date", ""), reverse=True)
        return jsonify(events[:50])

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
                "/api/system/uptime": {"get": {"summary": "System uptime dashboard", "tags": ["System"]}},
                "/api/logs": {"get": {"summary": "Log viewer (admin)", "tags": ["System"]}},
                "/api/workers": {"get": {"summary": "RQ workers info", "tags": ["System"]}},
                "/api/cache/stats": {"get": {"summary": "Cache analytics", "tags": ["System"]}},
                "/api/share": {"post": {"summary": "Create share link", "tags": ["Share"]}},
                "/api/shares": {"get": {"summary": "List shares", "tags": ["Share"]}},
                "/api/notifications": {"get": {"summary": "List notifications", "tags": ["Notifications"]}},
                "/api/notifications/unread-count": {"get": {"summary": "Unread count", "tags": ["Notifications"]}},
                "/api/notifications/mark-all-read": {"post": {"summary": "Mark all read", "tags": ["Notifications"]}},
                "/api/ai-chat": {"post": {"summary": "Chat with AI", "tags": ["AI"]}},
                "/api/price-forecast/{id}": {"get": {"summary": "Price trend forecast", "tags": ["Prices"]}},
                "/api/price-watch/{id}/tags": {"patch": {"summary": "Update price tags", "tags": ["Prices"]}},
                "/api/webhooks": {
                    "get": {"summary": "List webhooks", "tags": ["Webhooks"]},
                    "post": {"summary": "Add webhook", "tags": ["Webhooks"]},
                },
                "/api/webhooks/{id}": {"delete": {"summary": "Delete webhook", "tags": ["Webhooks"]}},
                "/api/email-digest/send": {"post": {"summary": "Send email digest", "tags": ["Email"]}},
                "/api/layout-presets": {"get": {"summary": "Layout presets", "tags": ["UI"]}},
                "/api/events-calendar": {"get": {"summary": "Events calendar", "tags": ["Calendar"]}},
                "/api/items/{id}/sentiment": {"get": {"summary": "Item sentiment", "tags": ["AI"]}},
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
