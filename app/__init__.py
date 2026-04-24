import atexit
import hashlib
import logging
import os
import uuid

from flask import Flask, g, request

from .config import Config
from .db import close_pool, init_db
from .metrics import mark_start, observe_request
from .finance_routes import register_finance_routes
from .routes import register_routes
from .scheduler import ScraperScheduler
from .utils import setup_logging


def create_app(start_scheduler: bool = True) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    setup_logging(
        app.config["LOG_LEVEL"],
        log_json=app.config["LOG_JSON"],
    )

    init_db(app.config["DATABASE_TARGET"])
    register_routes(app)
    register_finance_routes(app, app.extensions["limiter"])
    # ── Cache-bust helper for static assets ──────────────
    _static_hashes: dict[str, str] = {}

    def _asset_hash(filename: str) -> str:
        if filename in _static_hashes:
            return _static_hashes[filename]
        filepath = os.path.join(app.static_folder or "", filename)
        try:
            mtime = os.path.getmtime(filepath)
            h = hashlib.md5(f"{filename}:{mtime}".encode()).hexdigest()[:10]
        except OSError:
            h = "0"
        _static_hashes[filename] = h
        return h

    @app.context_processor
    def inject_asset_hash():
        return {"asset_hash": _asset_hash}

    @app.before_request
    def before_request_hooks():
        g.request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        g.request_started_at = mark_start()

    @app.after_request
    def after_request_hooks(response):
        started_at = g.get("request_started_at")
        if started_at is None:
            started_at = mark_start()

        response.headers["X-Request-Id"] = g.get("request_id", "")
        route = (
            request.url_rule.rule if request.url_rule else request.path
        )
        observe_request(
            method=request.method,
            route=route,
            status_code=response.status_code,
            started_at=started_at,
        )

        logging.getLogger("http").info(
            "request finished",
            extra={
                "request_id": g.get("request_id"),
            },
        )
        return response

    if start_scheduler:
        scheduler = ScraperScheduler(app)
        scheduler.start()
        setattr(app, "scheduler", scheduler)
        atexit.register(scheduler.shutdown)

    atexit.register(close_pool)
    return app
