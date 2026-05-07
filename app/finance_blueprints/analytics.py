"""Finance analytics routes."""

from __future__ import annotations


def register_analytics_routes(app, limiter, repo, cache, logger, helpers=None) -> None:
    if helpers is None:
        helpers = {}

    FINANCE_CACHE_TTLS = helpers.get("FINANCE_CACHE_TTLS", {})

    from flask import jsonify, request

    from ..security import sanitize_text

    @app.get("/api/finance/analytics")
    @limiter.limit("30/minute")
    def finance_analytics():
        month = sanitize_text(str(request.args.get("month", "")), 7).strip()
        if not month:
            return jsonify({"error": "month required"}), 400
        if len(month) != 7 or month[4] != "-":
            return jsonify({"error": "month invalid (YYYY-MM)"}), 400
        try:
            payload = repo.get_fin_analytics(month)
            return jsonify(payload or {})
        except Exception as ex:
            return jsonify({"error": str(ex)}), 500

    @app.get("/api/finance/budget-check")
    @limiter.limit("30/minute")
    def finance_budget_check():
        month = sanitize_text(str(request.args.get("month", "")), 7).strip()
        if not month:
            return jsonify({"error": "month required"}), 400
        try:
            alerts = repo.get_budget_alerts(month)
            return jsonify({"alerts": alerts or []})
        except Exception as ex:
            return jsonify({"error": str(ex)}), 500

    @app.get("/api/finance/health-score")
    @limiter.limit("30/minute")
    def finance_health_score():
        cache_key = "finance:health-score"
        cached = cache.get(cache_key)
        if cached:
            return jsonify(cached)
        try:
            payload = repo.get_fin_health_score()
            cache.set(cache_key, payload, FINANCE_CACHE_TTLS["summary"])
            return jsonify(payload)
        except Exception as ex:
            return jsonify({"error": str(ex)}), 500