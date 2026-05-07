"""Finance investment planning routes."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any


def register_investment_planning_routes(
    app,
    limiter,
    repo,
    cache,
    logger,
    helpers: dict[str, Any] | None = None,
) -> None:
    if helpers is None:
        helpers = {}

    FINANCE_CACHE_TTLS = helpers.get("FINANCE_CACHE_TTLS", {})
    _invalidate_cache_prefixes = helpers.get("_invalidate_cache_prefixes", lambda *args: None)

    from flask import jsonify, request

    from ..security import require_finance_key, sanitize_text

    @app.get("/api/finance/allocation-targets")
    @limiter.limit("30/minute")
    def finance_list_allocation_targets():
        cached = cache.get("finance:allocation-targets")
        if cached:
            return jsonify(cached)
        payload = repo.list_fin_allocation_targets()
        cache.set(
            "finance:allocation-targets",
            payload,
            FINANCE_CACHE_TTLS["allocation_targets"],
        )
        return jsonify(payload)

    @app.post("/api/finance/allocation-targets")
    @limiter.limit("15/minute")
    @require_finance_key
    def finance_save_allocation_targets():
        body = request.get_json(silent=True)
        if not body or not isinstance(body.get("targets"), list):
            return jsonify({"error": "targets array obrigatório"}), 400
        for target in body["targets"]:
            asset_type = sanitize_text(str(target.get("asset_type", "")), 20)
            target_pct = float(target.get("target_pct", 0))
            if asset_type:
                repo.upsert_fin_allocation_target(asset_type, target_pct)
        _invalidate_cache_prefixes("finance:allocation-targets")
        return jsonify({"ok": True})

    @app.get("/api/finance/rebalance")
    @limiter.limit("15/minute")
    def finance_rebalance():
        summary = repo.get_fin_summary()
        targets = repo.list_fin_allocation_targets()
        total_value = summary["current_value"]
        aporte = max(0.0, float(request.args.get("aporte", 0) or 0))
        total_after_aporte = total_value + aporte

        if not targets or total_value <= 0:
            return jsonify(
                {
                    "suggestions": [],
                    "message": "Configure suas metas de alocação primeiro.",
                    "total_value": total_value,
                    "aporte": aporte,
                    "total_after_aporte": total_after_aporte,
                }
            )

        target_map = {target["asset_type"]: target["target_pct"] for target in targets}
        current_alloc = summary.get("allocation", {})
        suggestions = []
        positive_gaps: list[dict[str, float | str]] = []
        for asset_type, target_pct in target_map.items():
            current_val = current_alloc.get(asset_type, 0)
            current_pct = (current_val / total_value * 100) if total_value else 0
            target_val = total_after_aporte * target_pct / 100
            diff_val = target_val - current_val
            diff_pct = target_pct - current_pct
            if diff_val > 0:
                positive_gaps.append({"asset_type": asset_type, "gap": diff_val})
            suggestions.append(
                {
                    "asset_type": asset_type,
                    "target_pct": round(target_pct, 1),
                    "current_pct": round(current_pct, 1),
                    "current_value": round(current_val, 2),
                    "target_value": round(target_val, 2),
                    "diff_value": round(diff_val, 2),
                    "diff_pct": round(diff_pct, 1),
                    "action": "comprar" if diff_val > 0 else "vender" if diff_val < 0 else "ok",
                    "aporte_sugerido": 0.0,
                }
            )

        if aporte > 0 and positive_gaps:
            total_gap = sum(float(gap["gap"]) for gap in positive_gaps) or 1.0
            allocation_map: dict[str, float] = {}
            for gap in positive_gaps:
                allocation_map[str(gap["asset_type"])] = round(
                    aporte * (float(gap["gap"]) / total_gap),
                    2,
                )
            for suggestion in suggestions:
                suggestion["aporte_sugerido"] = allocation_map.get(suggestion["asset_type"], 0.0)

        return jsonify(
            {
                "suggestions": suggestions,
                "total_value": total_value,
                "aporte": aporte,
                "total_after_aporte": total_after_aporte,
            }
        )

    @app.get("/api/finance/projection")
    @limiter.limit("20/minute")
    def finance_projection():
        summary = repo.get_fin_summary()
        current_value = max(0.0, float(summary.get("current_value", 0) or 0))
        months = min(600, max(1, int(request.args.get("months", 12) or 12)))
        aporte_mensal = max(0.0, float(request.args.get("aporte_mensal", 0) or 0))

        scenarios = {
            "conservador": 0.06,
            "base": 0.10,
            "otimista": 0.14,
        }

        result: dict[str, dict] = {}
        for name, annual_rate in scenarios.items():
            monthly_rate = (1 + annual_rate) ** (1 / 12) - 1
            value = current_value
            points: list[dict[str, float | int]] = [{"month": 0, "value": round(value, 2)}]
            for month in range(1, months + 1):
                value = value * (1 + monthly_rate) + aporte_mensal
                points.append({"month": month, "value": round(value, 2)})
            result[name] = {
                "annual_rate": annual_rate,
                "final_value": round(value, 2),
                "points": points,
            }

        return jsonify(
            {
                "current_value": round(current_value, 2),
                "months": months,
                "aporte_mensal": aporte_mensal,
                "scenarios": result,
            }
        )

    @app.get("/api/finance/dividend-ceiling")
    @limiter.limit("20/minute")
    def finance_dividend_ceiling():
        try:
            raw_target_dy = float(request.args.get("target_dy", 8.0) or 8.0)
        except (TypeError, ValueError):
            raw_target_dy = 8.0
        try:
            raw_months = int(request.args.get("months", 12) or 12)
        except (TypeError, ValueError):
            raw_months = 12
        target_dy = max(0.1, min(30.0, raw_target_dy))
        months = max(3, min(60, raw_months))
        cache_key = f"finance:dividend-ceiling:{target_dy:.2f}:{months}"
        cached = cache.get(cache_key)
        if cached:
            return jsonify(cached)

        summary = repo.get_fin_summary()
        portfolio = summary.get("portfolio", [])
        if not portfolio:
            payload = {
                "target_dy": target_dy,
                "months": months,
                "rows": [],
                "message": "Sem ativos em carteira para simular.",
            }
            cache.set(
                cache_key,
                payload,
                FINANCE_CACHE_TTLS["dividend_ceiling"],
            )
            return jsonify(payload)

        dividends = repo.list_fin_dividends(limit=5000)
        cutoff = datetime.now().replace(day=1)
        cutoff_month = cutoff.month - (months - 1)
        cutoff_year = cutoff.year
        while cutoff_month <= 0:
            cutoff_month += 12
            cutoff_year -= 1
        cutoff_key = f"{cutoff_year}-{str(cutoff_month).zfill(2)}"

        div_per_symbol: dict[str, float] = {}
        for dividend in dividends:
            symbol = str(dividend.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            pay_key = str(dividend.get("pay_date") or dividend.get("ex_date") or "")[:7]
            if pay_key and pay_key < cutoff_key:
                continue
            div_per_symbol[symbol] = (
                float(div_per_symbol.get(symbol, 0.0))
                + float(dividend.get("total_amount") or 0.0)
            )

        rows = []
        for position in portfolio:
            symbol = str(position.get("symbol") or "").strip().upper()
            qty = float(position.get("quantity") or 0.0)
            current_price = float(position.get("current_price") or 0.0)
            if not symbol or qty <= 0:
                continue

            total_div = float(div_per_symbol.get(symbol, 0.0))
            dps_ttm = (total_div / qty) if qty > 0 else 0.0
            ceiling_price = (
                dps_ttm / (target_dy / 100.0)
                if dps_ttm > 0
                else 0.0
            )
            implied_dy = (dps_ttm / current_price * 100.0) if current_price > 0 else 0.0
            upside = ((ceiling_price / current_price) - 1.0) * 100.0 if current_price > 0 else None

            signal = "neutro"
            if ceiling_price > 0 and current_price > 0:
                if current_price <= ceiling_price * 0.95:
                    signal = "atrativo"
                elif current_price > ceiling_price * 1.05:
                    signal = "caro"

            rows.append(
                {
                    "symbol": symbol,
                    "asset_type": position.get("asset_type") or "",
                    "current_price": round(current_price, 4),
                    "dps_ttm": round(dps_ttm, 4),
                    "ceiling_price": round(ceiling_price, 4),
                    "implied_dy": round(implied_dy, 2),
                    "upside_pct": round(float(upside), 2) if upside is not None else None,
                    "signal": signal,
                }
            )

        rows.sort(key=lambda row: (row.get("signal") != "atrativo", -(row.get("upside_pct") or -9999)))
        payload = {
            "target_dy": target_dy,
            "months": months,
            "rows": rows,
        }
        cache.set(cache_key, payload, FINANCE_CACHE_TTLS["dividend_ceiling"])
        return jsonify(payload)

    @app.get("/api/finance/independence-scenario")
    @limiter.limit("20/minute")
    def finance_independence_scenario():
        try:
            raw_target_income = float(
                request.args.get("target_monthly_income", 5000) or 5000,
            )
        except (TypeError, ValueError):
            raw_target_income = 5000.0
        try:
            raw_years = int(request.args.get("years", 20) or 20)
        except (TypeError, ValueError):
            raw_years = 20
        try:
            raw_aporte = float(request.args.get("aporte_mensal", 0) or 0)
        except (TypeError, ValueError):
            raw_aporte = 0.0
        try:
            raw_safe_rate = float(request.args.get("safe_rate_pct", 4.0) or 4.0)
        except (TypeError, ValueError):
            raw_safe_rate = 4.0

        target_monthly_income = max(0.0, raw_target_income)
        years = max(1, min(60, raw_years))
        aporte_mensal = max(0.0, raw_aporte)
        safe_rate_pct = max(1.0, min(12.0, raw_safe_rate))
        cache_key = (
            "finance:independence:"
            f"{target_monthly_income:.2f}:{years}:{aporte_mensal:.2f}:{safe_rate_pct:.2f}"
        )
        cached = cache.get(cache_key)
        if cached:
            return jsonify(cached)

        summary = repo.get_fin_summary()
        current_value = max(0.0, float(summary.get("current_value", 0) or 0))
        target_patrimony = (
            target_monthly_income * 12.0 / (safe_rate_pct / 100.0)
            if safe_rate_pct > 0
            else 0.0
        )
        months = years * 12

        scenarios = {
            "conservador": 0.06,
            "base": 0.10,
            "otimista": 0.14,
        }
        weights = {
            "conservador": 0.25,
            "base": 0.50,
            "otimista": 0.25,
        }

        result: dict[str, dict] = {}
        chance = 0.0
        for name, annual_rate in scenarios.items():
            monthly_rate = (1 + annual_rate) ** (1 / 12) - 1
            value = current_value
            reached_month = None
            for month in range(1, months + 1):
                value = value * (1 + monthly_rate) + aporte_mensal
                if reached_month is None and value >= target_patrimony:
                    reached_month = month
            reached = value >= target_patrimony
            if reached:
                chance += weights.get(name, 0.0)

            result[name] = {
                "annual_rate": annual_rate,
                "final_value": round(value, 2),
                "reached": reached,
                "reached_month": reached_month,
                "reached_year": (
                    datetime.now().year + math.ceil(reached_month / 12)
                    if reached_month
                    else None
                ),
                "gap": round(max(0.0, target_patrimony - value), 2),
            }

        payload = {
            "current_value": round(current_value, 2),
            "target_monthly_income": round(target_monthly_income, 2),
            "target_patrimony": round(target_patrimony, 2),
            "years": years,
            "months": months,
            "aporte_mensal": round(aporte_mensal, 2),
            "safe_rate_pct": round(safe_rate_pct, 2),
            "chance_percent": round(chance * 100.0, 1),
            "scenarios": result,
        }
        cache.set(cache_key, payload, FINANCE_CACHE_TTLS["independence"])
        return jsonify(payload)
