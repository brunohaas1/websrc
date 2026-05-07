"""Finance monthly comparison routes."""

from __future__ import annotations

from flask import jsonify, request


def register_monthly_comparison_routes(app, limiter, repo, cache, logger, helpers=None) -> None:
    if helpers is None:
        helpers = {}

    FINANCE_CACHE_TTLS = helpers.get("FINANCE_CACHE_TTLS", {})

    @app.get("/api/finance/cashflow/monthly-comparison")
    @limiter.limit("30/minute")
    def finance_cashflow_monthly_comparison():
        try:
            months = max(1, min(24, int(request.args.get("months", "12"))))
        except (TypeError, ValueError):
            months = 12
        cache_key = f"finance:monthly-comparison:{months}"
        cached = cache.get(cache_key)
        if cached is not None:
            return jsonify(cached)
        rows = repo.get_fin_cashflow_monthly_comparison(months=months)
        payload = {"months": months, "data": rows}
        cache.set(cache_key, payload, FINANCE_CACHE_TTLS.get("cashflow_summary", 300))
        return jsonify(payload)