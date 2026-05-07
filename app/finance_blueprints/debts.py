"""Finance debt routes."""

from __future__ import annotations

from flask import jsonify, request

from ..security import require_finance_key, sanitize_text


def register_debt_routes(app, limiter, repo, cache, logger, helpers=None) -> None:
    if helpers is None:
        helpers = {}

    FINANCE_CACHE_TTLS = helpers.get("FINANCE_CACHE_TTLS", {})

    @app.get("/api/finance/debts")
    @limiter.limit("60/minute")
    def finance_list_debts():
        status = sanitize_text(str(request.args.get("status", "")), 20).strip() or None
        return jsonify(repo.list_fin_debts(status=status))

    @app.post("/api/finance/debts")
    @require_finance_key
    @limiter.limit("60/minute")
    def finance_add_debt():
        data = request.get_json(silent=True) or {}
        creditor = sanitize_text(str(data.get("creditor") or ""), 120).strip()
        if not creditor:
            return jsonify({"error": "creditor é obrigatório"}), 400
        try:
            raw_current_balance = (
                data.get("current_balance")
                if data.get("current_balance") is not None
                else data.get("principal")
            )
            debt_id = repo.add_fin_debt({
                "creditor": creditor,
                "description": sanitize_text(str(data.get("description") or ""), 250),
                "principal": float(data.get("principal") or 0),
                "current_balance": float(raw_current_balance or 0),
                "interest_rate": float(data.get("interest_rate") or 0),
                "monthly_payment": float(data.get("monthly_payment") or 0),
                "due_date": sanitize_text(str(data.get("due_date") or ""), 10) or None,
                "status": sanitize_text(str(data.get("status") or "open"), 20),
                "category": sanitize_text(str(data.get("category") or "personal"), 50),
                "notes": sanitize_text(str(data.get("notes") or ""), 500) or None,
            })
            return jsonify({"id": debt_id, "status": "created"}), 201
        except Exception as ex:
            return jsonify({"error": str(ex)}), 500

    @app.put("/api/finance/debts/<int:debt_id>")
    @require_finance_key
    @limiter.limit("60/minute")
    def finance_update_debt(debt_id: int):
        data = request.get_json(silent=True) or {}
        payload: dict = {}
        if "creditor" in data:
            payload["creditor"] = sanitize_text(str(data["creditor"] or ""), 120).strip()
        if "description" in data:
            payload["description"] = sanitize_text(str(data["description"] or ""), 250)
        for num_field in ("principal", "current_balance", "interest_rate", "monthly_payment"):
            if num_field in data:
                payload[num_field] = float(data[num_field] or 0)
        if "due_date" in data:
            payload["due_date"] = sanitize_text(str(data["due_date"] or ""), 10) or None
        if "status" in data:
            payload["status"] = sanitize_text(str(data["status"] or "open"), 20)
        if "category" in data:
            payload["category"] = sanitize_text(str(data["category"] or "personal"), 50)
        if "notes" in data:
            payload["notes"] = sanitize_text(str(data["notes"] or ""), 500) or None
        try:
            updated = repo.update_fin_debt(debt_id, payload)
            if updated:
                return jsonify({"status": "updated"})
            return jsonify({"error": "not found"}), 404
        except Exception as ex:
            return jsonify({"error": str(ex)}), 500

    @app.delete("/api/finance/debts/<int:debt_id>")
    @require_finance_key
    @limiter.limit("30/minute")
    def finance_delete_debt(debt_id: int):
        deleted = repo.delete_fin_debt(debt_id)
        if deleted:
            return jsonify({"status": "deleted"})
        return jsonify({"error": "not found"}), 404

    @app.get("/api/finance/debts/summary")
    @limiter.limit("30/minute")
    def finance_debts_summary():
        cache_key = "finance:debts-summary"
        cached = cache.get(cache_key)
        if cached:
            return jsonify(cached)
        try:
            payload = repo.get_fin_debts_summary()
            cache.set(cache_key, payload, FINANCE_CACHE_TTLS["summary"])
            return jsonify(payload)
        except Exception as ex:
            return jsonify({"error": str(ex)}), 500

    @app.post("/api/finance/debts/<int:debt_id>/simulate")
    @limiter.limit("30/minute")
    def finance_simulate_debt(debt_id: int):
        data = request.get_json(silent=True) or {}
        extra = float(data.get("extra_payment") or 0)
        if extra < 0:
            return jsonify({"error": "extra_payment must be >= 0"}), 400
        try:
            result = repo.simulate_fin_debt_anticipation(debt_id, extra)
            return jsonify(result)
        except ValueError as ex:
            return jsonify({"error": str(ex)}), 404
        except Exception as ex:
            return jsonify({"error": str(ex)}), 500