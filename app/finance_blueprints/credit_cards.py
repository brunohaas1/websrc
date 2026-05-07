"""Finance credit card routes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def register_credit_card_routes(app, limiter, repo, cache, logger, helpers=None) -> None:
    if helpers is None:
        helpers = {}

    _audit = helpers.get("_audit", lambda *args, **kwargs: None)
    _is_finite_number = helpers.get("_is_finite_number", lambda value: True)

    from flask import jsonify, request

    from ..security import require_finance_key, sanitize_text

    @app.get("/api/finance/credit-cards")
    @limiter.limit("30/minute")
    def finance_list_credit_cards():
        return jsonify(repo.list_fin_credit_cards())

    @app.post("/api/finance/credit-cards")
    @limiter.limit("15/minute")
    @require_finance_key
    def finance_add_credit_card():
        body = request.get_json(silent=True) or {}
        name = sanitize_text(str(body.get("name", "")), 80).strip()
        if not name:
            return jsonify({"error": "name obrigatório"}), 400
        try:
            limit_amount = float(body.get("limit_amount", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "limit_amount inválido"}), 400
        if not _is_finite_number(limit_amount) or limit_amount < 0:
            return jsonify({"error": "limit_amount inválido"}), 400
        try:
            closing_day = int(body.get("closing_day", 1))
            due_day = int(body.get("due_day", 10))
        except (TypeError, ValueError):
            return jsonify({"error": "closing_day/due_day inválido"}), 400
        closing_day = max(1, min(31, closing_day))
        due_day = max(1, min(31, due_day))
        data = {
            "name": name,
            "limit_amount": round(limit_amount, 2),
            "closing_day": closing_day,
            "due_day": due_day,
            "notes": sanitize_text(str(body.get("notes", "")), 300),
        }
        card_id = repo.add_fin_credit_card(data)
        _audit("add", "credit_card", card_id, {"after": {**data, "id": card_id}})
        return jsonify({"ok": True, "id": card_id}), 201

    @app.put("/api/finance/credit-cards/<int:card_id>")
    @limiter.limit("15/minute")
    @require_finance_key
    def finance_update_credit_card(card_id: int):
        card = repo.get_fin_credit_card(card_id)
        if not card:
            return jsonify({"error": "Cartão não encontrado"}), 404
        body = request.get_json(silent=True) or {}
        data: dict = {}
        if "name" in body:
            name = sanitize_text(str(body["name"]), 80).strip()
            if not name:
                return jsonify({"error": "name não pode ser vazio"}), 400
            data["name"] = name
        if "limit_amount" in body:
            try:
                limit_amount = float(body["limit_amount"])
            except (TypeError, ValueError):
                return jsonify({"error": "limit_amount inválido"}), 400
            if not _is_finite_number(limit_amount) or limit_amount < 0:
                return jsonify({"error": "limit_amount inválido"}), 400
            data["limit_amount"] = round(limit_amount, 2)
        if "closing_day" in body:
            data["closing_day"] = max(1, min(31, int(body["closing_day"])))
        if "due_day" in body:
            data["due_day"] = max(1, min(31, int(body["due_day"])))
        if "notes" in body:
            data["notes"] = sanitize_text(str(body["notes"]), 300)
        if not data:
            return jsonify({"error": "Nenhum campo para atualizar"}), 400
        repo.update_fin_credit_card(card_id, data)
        _audit("update", "credit_card", card_id, {"fields": sorted(data.keys())})
        return jsonify({"ok": True})

    @app.get("/api/finance/credit-cards/<int:card_id>/usage")
    @limiter.limit("30/minute")
    def finance_credit_card_usage(card_id: int):
        import calendar as _cal

        card = repo.get_fin_credit_card(card_id)
        if not card:
            return jsonify({"error": "Cartão não encontrado"}), 404
        closing_day = max(1, min(31, int(card.get("closing_day") or 1)))
        today = datetime.now(timezone.utc).date()
        last_day = _cal.monthrange(today.year, today.month)[1]
        cycle_day = min(closing_day, last_day)
        if today.day >= cycle_day:
            since = today.replace(day=cycle_day)
        else:
            prev = today.replace(day=1) - timedelta(days=1)
            prev_last = _cal.monthrange(prev.year, prev.month)[1]
            since = prev.replace(day=min(closing_day, prev_last))
        usage = repo.get_fin_cashflow_cycle_usage(card_id, since.isoformat())
        return jsonify({
            "card_id": card_id,
            "since_date": since.isoformat(),
            "spent": usage["spent"],
            "count": usage["count"],
            "limit_amount": float(card.get("limit_amount") or 0),
        })

    @app.delete("/api/finance/credit-cards/<int:card_id>")
    @limiter.limit("15/minute")
    @require_finance_key
    def finance_delete_credit_card(card_id: int):
        card = repo.get_fin_credit_card(card_id)
        if not card:
            return jsonify({"error": "Cartão não encontrado"}), 404
        repo.delete_fin_credit_card(card_id)
        _audit("delete", "credit_card", card_id, None)
        return jsonify({"ok": True})