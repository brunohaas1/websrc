"""Finance goals routes."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any


def register_goals_routes(app, limiter, repo, cache, logger, helpers=None) -> None:
    if helpers is None:
        helpers = {}

    _audit = helpers.get("_audit", lambda *args, **kwargs: None)
    _invalidate_cache_prefixes = helpers.get("_invalidate_cache_prefixes", lambda *args: None)
    _is_finite_number = helpers.get("_is_finite_number", lambda value: True)
    FINANCE_CACHE_TTLS = helpers.get("FINANCE_CACHE_TTLS", {})

    from flask import jsonify, request

    from ..security import require_finance_key, sanitize_text

    @app.get("/api/finance/goals")
    @limiter.limit("30/minute")
    def finance_list_goals():
        return jsonify(repo.list_fin_goals())

    @app.post("/api/finance/goals")
    @limiter.limit("15/minute")
    @require_finance_key
    def finance_add_goal():
        body = request.get_json(silent=True)
        if not body or not body.get("name") or not body.get("target_amount"):
            return jsonify({"error": "name e target_amount obrigatórios"}), 400
        data = {
            "name": sanitize_text(str(body["name"]), 100),
            "target_amount": float(body["target_amount"]),
            "current_amount": float(body.get("current_amount", 0)),
            "deadline": str(body.get("deadline", "")) or None,
            "category": sanitize_text(str(body.get("category", "savings")), 30),
            "notes": sanitize_text(str(body.get("notes", "")), 500),
        }
        goal_id = repo.add_fin_goal(data)
        _invalidate_cache_prefixes("finance:audit:")
        return jsonify({"ok": True, "id": goal_id}), 201

    @app.put("/api/finance/goals/<int:goal_id>")
    @limiter.limit("15/minute")
    @require_finance_key
    def finance_update_goal(goal_id: int):
        body = request.get_json(silent=True)
        if not body:
            return jsonify({"error": "JSON inválido"}), 400
        data: dict[str, Any] = {}
        if "name" in body:
            data["name"] = sanitize_text(str(body["name"]), 100)
        if "target_amount" in body:
            data["target_amount"] = float(body["target_amount"])
        if "current_amount" in body:
            data["current_amount"] = float(body["current_amount"])
        if "deadline" in body:
            data["deadline"] = str(body["deadline"]) or None
        if "category" in body:
            data["category"] = sanitize_text(str(body["category"]), 30)
        if "notes" in body:
            data["notes"] = sanitize_text(str(body["notes"]), 500)
        repo.update_fin_goal(goal_id, data)
        _invalidate_cache_prefixes("finance:audit:")
        return jsonify({"ok": True})

    @app.delete("/api/finance/goals/<int:goal_id>")
    @limiter.limit("15/minute")
    @require_finance_key
    def finance_delete_goal(goal_id: int):
        repo.delete_fin_goal(goal_id)
        _invalidate_cache_prefixes("finance:audit:")
        return jsonify({"ok": True})

    @app.post("/api/finance/goals/<int:goal_id>/scenario")
    @limiter.limit("20/minute")
    def finance_goal_scenario(goal_id: int):
        goal = repo.get_fin_goal(goal_id)
        if not goal:
            return jsonify({"error": "Meta não encontrada"}), 404

        body = request.get_json(silent=True) or {}
        month = sanitize_text(str(body.get("month", "")), 7).strip() or datetime.now(timezone.utc).strftime("%Y-%m")
        if not re.match(r"^\d{4}-\d{2}$", month):
            return jsonify({"error": "month inválido (use YYYY-MM)"}), 400

        try:
            extra_monthly = float(body.get("extra_monthly", 0) or 0)
        except (TypeError, ValueError):
            extra_monthly = 0.0
        extra_monthly = max(0.0, extra_monthly)

        adjustments = body.get("adjustments", [])
        if not isinstance(adjustments, list):
            adjustments = []

        scenario = repo.get_fin_cashflow_analytics(month=month)
        expense_by_cat = {
            str(category.get("category") or ""): float(category.get("amount") or 0)
            for category in scenario.get("categories", {}).get("expense", [])
        }
        reduction_saving = 0.0
        for adjustment in adjustments:
            cat = sanitize_text(str(adjustment.get("category") or ""), 60).strip()
            try:
                pct = float(adjustment.get("reduction_pct") or 0)
            except (TypeError, ValueError):
                pct = 0.0
            pct = max(0.0, min(100.0, pct))
            if cat:
                reduction_saving += expense_by_cat.get(cat, 0.0) * (pct / 100.0)

        summary = repo.get_fin_cashflow_summary(months=3)
        monthly_rows = summary.get("monthly", [])
        positive_balances = [
            float(row.get("balance") or 0)
            for row in monthly_rows
            if float(row.get("balance") or 0) > 0
        ]
        baseline_monthly = (sum(positive_balances) / len(positive_balances)) if positive_balances else 0.0

        target = float(goal.get("target_amount") or 0)
        current = float(goal.get("current_amount") or 0)
        gap = max(0.0, target - current)

        baseline_contribution = max(0.0, baseline_monthly)
        scenario_contribution = max(0.0, baseline_monthly + extra_monthly + reduction_saving)

        def _months_needed(monthly_contrib: float) -> int | None:
            if gap <= 0:
                return 0
            if monthly_contrib <= 0:
                return None
            return int(math.ceil(gap / monthly_contrib))

        baseline_months = _months_needed(baseline_contribution)
        simulated_months = _months_needed(scenario_contribution)

        return jsonify({
            "goal": {
                "id": int(goal.get("id") or goal_id),
                "name": goal.get("name"),
                "target_amount": round(target, 2),
                "current_amount": round(current, 2),
                "gap": round(gap, 2),
            },
            "assumptions": {
                "month": month,
                "baseline_monthly_contribution": round(baseline_contribution, 2),
                "extra_monthly": round(extra_monthly, 2),
                "monthly_saving_from_reduction": round(reduction_saving, 2),
            },
            "projection": {
                "baseline_months_to_goal": baseline_months,
                "simulated_months_to_goal": simulated_months,
                "months_saved": (
                    baseline_months - simulated_months
                    if baseline_months is not None and simulated_months is not None
                    else None
                ),
            },
        })

    @app.post("/api/finance/goals/<int:goal_id>/deposit")
    @limiter.limit("15/minute")
    @require_finance_key
    def finance_goal_deposit(goal_id: int):
        goal = repo.get_fin_goal(goal_id)
        if not goal:
            return jsonify({"error": "Meta não encontrada"}), 404
        body = request.get_json(silent=True) or {}
        if "amount" not in body:
            return jsonify({"error": "amount obrigatório"}), 400
        try:
            amount = float(body["amount"])
        except (TypeError, ValueError):
            return jsonify({"error": "amount inválido"}), 400
        if not _is_finite_number(amount) or amount <= 0:
            return jsonify({"error": "amount deve ser > 0"}), 400
        current = float(goal.get("current_amount") or 0)
        new_current = current + amount
        repo.update_fin_goal(goal_id, {"current_amount": round(new_current, 2)})
        _invalidate_cache_prefixes("finance:audit:")
        return jsonify({
            "ok": True,
            "id": goal_id,
            "current_amount": round(new_current, 2),
            "target_amount": round(float(goal.get("target_amount") or 0), 2),
        })

    @app.get("/api/finance/goals/passive-income")
    @limiter.limit("30/minute")
    def finance_get_passive_income_goal():
        cache_key = "finance:passive-income-goal"
        cached = cache.get(cache_key)
        if cached:
            return jsonify(cached)

        raw_target = repo.get_setting("finance_passive_income_goal_monthly", "0")
        raw_note = repo.get_setting("finance_passive_income_goal_note", "")
        try:
            target_monthly = float(raw_target or 0)
        except (TypeError, ValueError):
            target_monthly = 0.0
        if not math.isfinite(target_monthly) or target_monthly < 0:
            target_monthly = 0.0

        payload = {
            "target_monthly": target_monthly,
            "note": sanitize_text(str(raw_note or ""), 500),
        }
        cache.set(cache_key, payload, FINANCE_CACHE_TTLS["passive_income_goal"])
        return jsonify(payload)

    @app.put("/api/finance/goals/passive-income")
    @limiter.limit("15/minute")
    @require_finance_key
    def finance_set_passive_income_goal():
        body = request.get_json(silent=True) or {}
        if "target_monthly" not in body:
            return jsonify({"error": "target_monthly obrigatório"}), 400
        try:
            target_monthly = float(body.get("target_monthly", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "target_monthly inválido"}), 400
        if not math.isfinite(target_monthly) or target_monthly < 0:
            return jsonify({"error": "target_monthly inválido"}), 400

        note = sanitize_text(str(body.get("note", "")), 500)
        repo.set_setting("finance_passive_income_goal_monthly", f"{target_monthly:.2f}")
        repo.set_setting("finance_passive_income_goal_note", note)
        _invalidate_cache_prefixes("finance:passive-income-goal")
        _audit("update", "passive_income_goal", None, {"target_monthly": target_monthly})
        return jsonify({
            "ok": True,
            "target_monthly": target_monthly,
            "note": note,
        })