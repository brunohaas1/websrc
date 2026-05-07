"""Finance watchlist routes."""

from __future__ import annotations

from typing import Any


def register_watchlist_routes(
    app,
    limiter,
    repo,
    cache,
    logger,
    helpers: dict[str, Any] | None = None,
) -> None:
    if helpers is None:
        helpers = {}

    _audit = helpers.get("_audit", lambda *args, **kwargs: None)
    _invalidate_financial_state_cache = helpers.get(
        "_invalidate_financial_state_cache",
        lambda **kwargs: None,
    )
    _is_finite_number = helpers.get("_is_finite_number", lambda value: True)

    from flask import jsonify, request

    from ..security import require_finance_key, sanitize_text

    @app.get("/api/finance/watchlist")
    @limiter.limit("30/minute")
    def finance_list_watchlist():
        return jsonify(repo.list_fin_watchlist())

    @app.post("/api/finance/watchlist")
    @limiter.limit("15/minute")
    @require_finance_key
    def finance_add_watchlist():
        body = request.get_json(silent=True)
        if not body or not body.get("symbol"):
            return jsonify({"error": "symbol obrigatório"}), 400
        data = {
            "symbol": sanitize_text(str(body["symbol"]).upper().strip(), 20),
            "name": sanitize_text(str(body.get("name", body["symbol"])), 100),
            "asset_type": sanitize_text(
                str(body.get("asset_type", "stock")), 20,
            ),
            "target_price": float(body["target_price"]) if body.get("target_price") else None,
            "alert_above": bool(body.get("alert_above")),
            "notes": sanitize_text(str(body.get("notes", "")), 500),
        }
        if data["target_price"] is not None:
            if not _is_finite_number(data["target_price"]) or data["target_price"] < 0:
                return jsonify({"error": "target_price inválido"}), 400
        wl_id = repo.add_fin_watchlist(data)
        _audit("add", "watchlist", wl_id, {"symbol": data["symbol"]})
        return jsonify({"ok": True, "id": wl_id, "status": "updated"}), 201

    @app.delete("/api/finance/watchlist/<int:wl_id>")
    @limiter.limit("15/minute")
    @require_finance_key
    def finance_delete_watchlist(wl_id: int):
        repo.delete_fin_watchlist(wl_id)
        _audit("delete", "watchlist", wl_id, None)
        _invalidate_financial_state_cache(include_market=True)
        return jsonify({"ok": True})

    @app.put("/api/finance/watchlist/<int:wl_id>")
    @limiter.limit("15/minute")
    @require_finance_key
    def finance_update_watchlist(wl_id: int):
        body = request.get_json(silent=True)
        if not body:
            return jsonify({"error": "JSON inválido"}), 400
        data: dict[str, Any] = {}
        if "name" in body:
            data["name"] = sanitize_text(str(body["name"]), 100)
        if "asset_type" in body:
            data["asset_type"] = sanitize_text(str(body["asset_type"]), 20)
        if "target_price" in body:
            data["target_price"] = float(body["target_price"]) if body["target_price"] else None
            if data["target_price"] is not None:
                if not _is_finite_number(data["target_price"]) or data["target_price"] < 0:
                    return jsonify({"error": "target_price inválido"}), 400
        if "alert_above" in body:
            data["alert_above"] = bool(body["alert_above"])
        if "notes" in body:
            data["notes"] = sanitize_text(str(body["notes"]), 500)
        if not repo.update_fin_watchlist(wl_id, data):
            return jsonify({"error": "Item não encontrado"}), 404
        _audit("update", "watchlist", wl_id, {"fields": sorted(list(data.keys()))})
        _invalidate_financial_state_cache(include_market=True)
        return jsonify({"ok": True, "status": "updated"})