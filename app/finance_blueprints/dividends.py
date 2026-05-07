"""Finance dividends routes."""

from __future__ import annotations

from typing import Any


def register_dividends_routes(
    app,
    limiter,
    repo,
    cache,
    logger,
    helpers: dict[str, Any] | None = None,
) -> None:
    if helpers is None:
        helpers = {}

    _invalidate_financial_state_cache = helpers.get(
        "_invalidate_financial_state_cache",
        lambda **kwargs: None,
    )
    FINANCE_CACHE_TTLS = helpers.get("FINANCE_CACHE_TTLS", {"dividend_summary": 120})

    from datetime import datetime

    from flask import jsonify, request

    from ..security import require_finance_key, sanitize_text

    @app.get("/api/finance/dividends")
    @limiter.limit("30/minute")
    def finance_list_dividends():
        asset_id = request.args.get("asset_id", type=int)
        return jsonify(repo.list_fin_dividends(asset_id=asset_id))

    @app.post("/api/finance/dividends")
    @limiter.limit("15/minute")
    @require_finance_key
    def finance_add_dividend():
        body = request.get_json(silent=True)
        if not body or not body.get("asset_id"):
            return jsonify({"error": "asset_id obrigatório"}), 400
        data = {
            "asset_id": int(body["asset_id"]),
            "div_type": sanitize_text(
                str(body.get("div_type", "dividend")), 20,
            ),
            "amount_per_share": float(body.get("amount_per_share", 0)),
            "total_amount": float(body.get("total_amount", 0)),
            "quantity": float(body.get("quantity", 0)),
            "ex_date": str(body.get("ex_date", "")) or None,
            "pay_date": str(body.get("pay_date", ""))
            or datetime.now().strftime("%Y-%m-%d"),
            "notes": sanitize_text(str(body.get("notes", "")), 500),
        }
        if (
            data["amount_per_share"] > 0
            and data["quantity"] > 0
            and not data["total_amount"]
        ):
            data["total_amount"] = data["amount_per_share"] * data["quantity"]
        try:
            div_id = repo.add_fin_dividend(data)
        except ValueError as exc:
            if "duplicado" in str(exc).lower():
                return jsonify({"error": str(exc)}), 409
            raise
        _invalidate_financial_state_cache(include_dividends=True)
        return jsonify({"ok": True, "id": div_id}), 201

    @app.delete("/api/finance/dividends/<int:div_id>")
    @limiter.limit("15/minute")
    @require_finance_key
    def finance_delete_dividend(div_id: int):
        repo.delete_fin_dividend(div_id)
        _invalidate_financial_state_cache(include_dividends=True)
        return jsonify({"ok": True})

    @app.get("/api/finance/dividend-summary")
    @limiter.limit("30/minute")
    def finance_dividend_summary():
        cached = cache.get("finance:dividend-summary")
        if cached:
            return jsonify(cached)
        payload = repo.get_fin_dividend_summary()
        cache.set(
            "finance:dividend-summary",
            payload,
            FINANCE_CACHE_TTLS["dividend_summary"],
        )
        return jsonify(payload)
