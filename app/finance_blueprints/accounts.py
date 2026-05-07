"""Finance account routes."""

from __future__ import annotations


def register_account_routes(app, limiter, repo, cache, logger, helpers=None) -> None:
    if helpers is None:
        helpers = {}

    _audit = helpers.get("_audit", lambda *args, **kwargs: None)
    _is_finite_number = helpers.get("_is_finite_number", lambda value: True)

    from flask import jsonify, request

    from ..security import require_finance_key, sanitize_text

    @app.get("/api/finance/accounts")
    @limiter.limit("30/minute")
    def finance_list_accounts():
        return jsonify(repo.list_fin_accounts())

    @app.post("/api/finance/accounts")
    @limiter.limit("15/minute")
    @require_finance_key
    def finance_add_account():
        body = request.get_json(silent=True) or {}
        name = sanitize_text(str(body.get("name", "")), 100).strip()
        if not name:
            return jsonify({"error": "name obrigatório"}), 400

        account_type = sanitize_text(str(body.get("account_type", "bank")), 40).strip() or "bank"
        currency = sanitize_text(str(body.get("currency", "BRL")), 10).strip() or "BRL"

        try:
            initial_balance = float(body.get("initial_balance", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "initial_balance inválido"}), 400
        if not _is_finite_number(initial_balance):
            return jsonify({"error": "initial_balance inválido"}), 400

        account_id = repo.add_fin_account(
            {
                "name": name,
                "account_type": account_type,
                "currency": currency,
                "initial_balance": round(initial_balance, 2),
            }
        )
        _audit("add", "account", account_id, {"after": {"id": account_id, "name": name}})
        return jsonify({"ok": True, "id": account_id}), 201

    @app.put("/api/finance/accounts/<int:account_id>")
    @limiter.limit("15/minute")
    @require_finance_key
    def finance_update_account(account_id: int):
        body = request.get_json(silent=True) or {}
        if not body:
            return jsonify({"error": "JSON inválido"}), 400

        data: dict = {}
        if "name" in body:
            name = sanitize_text(str(body.get("name", "")), 100).strip()
            if not name:
                return jsonify({"error": "name obrigatório"}), 400
            data["name"] = name
        if "account_type" in body:
            data["account_type"] = sanitize_text(str(body.get("account_type", "bank")), 40).strip() or "bank"
        if "currency" in body:
            data["currency"] = sanitize_text(str(body.get("currency", "BRL")), 10).strip() or "BRL"
        if "initial_balance" in body:
            try:
                initial_balance = float(body.get("initial_balance", 0))
            except (TypeError, ValueError):
                return jsonify({"error": "initial_balance inválido"}), 400
            if not _is_finite_number(initial_balance):
                return jsonify({"error": "initial_balance inválido"}), 400
            data["initial_balance"] = round(initial_balance, 2)

        if not data:
            return jsonify({"error": "Nenhum campo para atualizar"}), 400

        ok = repo.update_fin_account(account_id, data)
        if not ok:
            return jsonify({"error": "Conta não encontrada"}), 404
        _audit("update", "account", account_id, {"fields": sorted(list(data.keys()))})
        return jsonify({"ok": True})

    @app.delete("/api/finance/accounts/<int:account_id>")
    @limiter.limit("15/minute")
    @require_finance_key
    def finance_delete_account(account_id: int):
        ok = repo.delete_fin_account(account_id)
        if not ok:
            return jsonify({"error": "Conta não encontrada"}), 404
        _audit("delete", "account", account_id, None)
        return jsonify({"ok": True})

    @app.get("/api/finance/accounts/balances")
    @limiter.limit("30/minute")
    def finance_accounts_balances():
        return jsonify(repo.get_fin_accounts_balance_summary())