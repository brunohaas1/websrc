"""Finance assets, portfolio, and transactions routes."""

from __future__ import annotations

from typing import Any


def register_assets_routes(
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
    _recalc_portfolio = helpers.get("_recalc_portfolio", lambda repo_obj, asset_id: None)
    finance_asset_history_alt = helpers.get("finance_asset_history_alt")

    from datetime import datetime

    from flask import jsonify, request

    from ..security import require_finance_key, sanitize_text

    @app.get("/api/finance/assets")
    @limiter.limit("30/minute")
    def finance_list_assets():
        return jsonify(repo.list_fin_assets())

    @app.post("/api/finance/assets")
    @limiter.limit("15/minute")
    @require_finance_key
    def finance_add_asset():
        body = request.get_json(silent=True)
        if not body or not body.get("symbol"):
            return jsonify({"error": "symbol obrigatório"}), 400
        extra = body.get("extra") or {}
        if not isinstance(extra, dict):
            extra = {}
        data = {
            "symbol": sanitize_text(str(body["symbol"]).upper().strip(), 20),
            "name": sanitize_text(str(body.get("name", body["symbol"])), 100),
            "asset_type": sanitize_text(
                str(body.get("asset_type", "stock")), 20,
            ),
            "currency": sanitize_text(str(body.get("currency", "BRL")), 10),
            "extra": extra,
        }
        asset_id = repo.upsert_fin_asset(data)
        _invalidate_financial_state_cache(include_market=True)
        return jsonify({"ok": True, "id": asset_id, "status": "created"}), 201

    @app.delete("/api/finance/assets/<int:asset_id>")
    @limiter.limit("15/minute")
    @require_finance_key
    def finance_delete_asset(asset_id: int):
        repo.delete_fin_asset(asset_id)
        _invalidate_financial_state_cache(include_market=True)
        return jsonify({"ok": True})

    @app.get("/api/finance/assets/<int:asset_id>/history")
    @limiter.limit("30/minute")
    def finance_asset_history(asset_id: int):
        if finance_asset_history_alt is None:
            return jsonify([])
        return finance_asset_history_alt(asset_id)

    @app.get("/api/finance/portfolio")
    @limiter.limit("30/minute")
    def finance_portfolio():
        return jsonify(repo.get_fin_portfolio())

    @app.get("/api/finance/transactions")
    @limiter.limit("30/minute")
    def finance_list_transactions():
        asset_id = request.args.get("asset_id", type=int)
        limit = min(200, max(1, int(request.args.get("limit", "50"))))
        page_str = request.args.get("page")
        page = max(1, int(page_str or "1"))
        offset = (page - 1) * limit
        rows = repo.list_fin_transactions(asset_id, limit=limit, offset=offset)
        if page_str is None:
            return jsonify(rows)
        return jsonify({
            "items": rows,
            "page": page,
            "per_page": limit,
            "has_more": len(rows) == limit,
        })

    @app.post("/api/finance/transactions")
    @limiter.limit("15/minute")
    @require_finance_key
    def finance_add_transaction():
        body = request.get_json(silent=True)
        if not body:
            return jsonify({"error": "JSON inválido"}), 400
        required = ["asset_id", "quantity", "price"]
        missing = [key for key in required if key not in body]
        if missing:
            return jsonify({"error": f"Campos: {', '.join(missing)}"}), 400
        try:
            qty = float(body["quantity"])
            price = float(body["price"])
            fees = float(body.get("fees", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "Valores numéricos inválidos"}), 400
        if not all(_is_finite_number(value) for value in (qty, price, fees)):
            return jsonify({"error": "Valores numéricos inválidos"}), 400
        if qty <= 0 or price < 0 or fees < 0:
            return jsonify({"error": "quantity > 0, price >= 0 e fees >= 0"}), 400
        tx_type = str(body.get("tx_type", "buy")).strip().lower()
        if tx_type not in ("buy", "sell"):
            return jsonify({"error": "tx_type: buy ou sell"}), 400
        total = qty * price + fees
        tx_date = str(body.get("tx_date", "")).strip()
        if not tx_date:
            tx_date = datetime.now().strftime("%Y-%m-%d")
        data = {
            "asset_id": int(body["asset_id"]),
            "tx_type": tx_type,
            "quantity": qty,
            "price": price,
            "total": total,
            "fees": fees,
            "notes": sanitize_text(str(body.get("notes", "")), 500),
            "tx_date": tx_date,
        }
        try:
            tx_id = repo.add_fin_transaction(data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 409

        _recalc_portfolio(repo, data["asset_id"])
        _audit("add", "transaction", tx_id, {"asset_id": data["asset_id"], "tx_type": tx_type})
        _invalidate_financial_state_cache()
        return jsonify({"ok": True, "id": tx_id}), 201

    @app.delete("/api/finance/transactions/<int:tx_id>")
    @limiter.limit("15/minute")
    @require_finance_key
    def finance_delete_transaction(tx_id: int):
        tx = repo.get_fin_transaction(tx_id)
        asset_id = tx.get("asset_id") if tx else None
        repo.delete_fin_transaction(tx_id)
        if asset_id:
            _recalc_portfolio(repo, asset_id)
        _audit("delete", "transaction", tx_id, {"asset_id": asset_id})
        _invalidate_financial_state_cache()
        return jsonify({"ok": True})

    @app.put("/api/finance/transactions/<int:tx_id>")
    @limiter.limit("15/minute")
    @require_finance_key
    def finance_update_transaction(tx_id: int):
        body = request.get_json(silent=True)
        if not body:
            return jsonify({"error": "JSON inválido"}), 400
        tx = repo.get_fin_transaction(tx_id)
        if not tx:
            return jsonify({"error": "Transação não encontrada"}), 404
        data: dict[str, Any] = {}
        if "tx_type" in body:
            tx_type = str(body["tx_type"]).strip().lower()
            if tx_type not in ("buy", "sell"):
                return jsonify({"error": "tx_type: buy ou sell"}), 400
            data["tx_type"] = tx_type
        try:
            if "quantity" in body:
                data["quantity"] = float(body["quantity"])
            if "price" in body:
                data["price"] = float(body["price"])
            if "fees" in body:
                data["fees"] = float(body["fees"])
        except (TypeError, ValueError):
            return jsonify({"error": "Valores numéricos inválidos"}), 400
        for key in ("quantity", "price", "fees"):
            if key in data and not _is_finite_number(data[key]):
                return jsonify({"error": "Valores numéricos inválidos"}), 400
        if "quantity" in data and data["quantity"] <= 0:
            return jsonify({"error": "quantity deve ser > 0"}), 400
        if "price" in data and data["price"] < 0:
            return jsonify({"error": "price deve ser >= 0"}), 400
        if "fees" in data and data["fees"] < 0:
            return jsonify({"error": "fees deve ser >= 0"}), 400
        if "notes" in body:
            data["notes"] = sanitize_text(str(body["notes"]), 500)
        if "tx_date" in body:
            data["tx_date"] = str(body["tx_date"])
        qty = data.get("quantity", tx.get("quantity", 0))
        price = data.get("price", tx.get("price", 0))
        fees = data.get("fees", tx.get("fees", 0))
        data["total"] = qty * price + fees
        repo.update_fin_transaction(tx_id, data)
        _recalc_portfolio(repo, tx["asset_id"])
        _audit("update", "transaction", tx_id, {"fields": sorted(list(data.keys()))})
        _invalidate_financial_state_cache()
        return jsonify({"ok": True})

    @app.put("/api/finance/transactions/batch")
    @limiter.limit("10/minute")
    @require_finance_key
    def finance_batch_update_transactions():
        body = request.get_json(silent=True) or {}
        tx_ids_raw = body.get("tx_ids") or []
        if not isinstance(tx_ids_raw, list) or not tx_ids_raw:
            return jsonify({"error": "tx_ids obrigatório"}), 400
        try:
            tx_ids = sorted({int(value) for value in tx_ids_raw if int(value) > 0})
        except (TypeError, ValueError):
            return jsonify({"error": "tx_ids inválido"}), 400
        updates = body.get("updates") or {}
        if not isinstance(updates, dict) or not updates:
            return jsonify({"error": "updates obrigatório"}), 400

        data: dict[str, Any] = {}
        if "tx_type" in updates:
            tx_type = str(updates["tx_type"]).strip().lower()
            if tx_type not in ("buy", "sell"):
                return jsonify({"error": "tx_type: buy ou sell"}), 400
            data["tx_type"] = tx_type
        try:
            if "fees" in updates:
                data["fees"] = float(updates["fees"])
            if "quantity" in updates:
                data["quantity"] = float(updates["quantity"])
            if "price" in updates:
                data["price"] = float(updates["price"])
        except (TypeError, ValueError):
            return jsonify({"error": "Valores numéricos inválidos"}), 400
        for key in ("quantity", "price", "fees"):
            if key in data and not _is_finite_number(data[key]):
                return jsonify({"error": "Valores numéricos inválidos"}), 400
        if "quantity" in data and data["quantity"] <= 0:
            return jsonify({"error": "quantity deve ser > 0"}), 400
        if "price" in data and data["price"] < 0:
            return jsonify({"error": "price deve ser >= 0"}), 400
        if "fees" in data and data["fees"] < 0:
            return jsonify({"error": "fees deve ser >= 0"}), 400
        if "notes" in updates:
            mode = str(updates.get("notes_mode", "replace")).strip().lower()
            notes = sanitize_text(str(updates.get("notes", "")), 500)
            if mode == "append":
                txs = repo.list_fin_transactions(limit=5000)
                by_id = {int(tx["id"]): tx for tx in txs}
                updated = 0
                for tx_id in tx_ids:
                    tx = by_id.get(tx_id)
                    if not tx:
                        continue
                    cur_notes = str(tx.get("notes") or "").strip()
                    merged = (f"{cur_notes} | {notes}" if cur_notes and notes else (notes or cur_notes)).strip()
                    ok = repo.update_fin_transaction(tx_id, {"notes": merged})
                    if ok:
                        updated += 1
                        _recalc_portfolio(repo, int(tx["asset_id"]))
                _invalidate_financial_state_cache()
                _audit("batch_update", "transaction", None, {"count": updated, "tx_ids": tx_ids, "fields": ["notes"]})
                return jsonify({"ok": True, "updated": updated})
            data["notes"] = notes

        updated = 0
        touched_assets: set[int] = set()
        txs = repo.list_fin_transactions(limit=5000)
        by_id = {int(tx["id"]): tx for tx in txs}
        for tx_id in tx_ids:
            tx = by_id.get(tx_id)
            if not tx:
                continue
            update_payload = dict(data)
            if "quantity" in update_payload or "price" in update_payload or "fees" in update_payload:
                qty = update_payload.get("quantity", tx.get("quantity", 0))
                price = update_payload.get("price", tx.get("price", 0))
                fees = update_payload.get("fees", tx.get("fees", 0))
                update_payload["total"] = float(qty) * float(price) + float(fees)
            ok = repo.update_fin_transaction(tx_id, update_payload)
            if ok:
                updated += 1
                touched_assets.add(int(tx["asset_id"]))
        for asset_id in touched_assets:
            _recalc_portfolio(repo, asset_id)
        _invalidate_financial_state_cache()
        _audit("batch_update", "transaction", None, {"count": updated, "tx_ids": tx_ids, "fields": sorted(list(data.keys()))})
        return jsonify({"ok": True, "updated": updated})