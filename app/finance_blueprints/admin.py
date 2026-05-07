"""Finance administrative routes."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


def register_admin_routes(app, limiter, repo, cache, logger, helpers=None) -> None:
    if helpers is None:
        helpers = {}

    FINANCE_SETTINGS_SCHEMA = helpers["FINANCE_SETTINGS_SCHEMA"]
    _bool_to_01 = helpers["_bool_to_01"]
    _validate_fin_setting = helpers["_validate_fin_setting"]
    _invalidate_financial_state_cache = helpers["_invalidate_financial_state_cache"]
    _provider_day_metrics = helpers["_provider_day_metrics"]

    from flask import jsonify, request

    from ..security import require_finance_key

    @app.get("/api/finance/settings")
    @limiter.limit("20/minute")
    @require_finance_key
    def finance_get_settings():
        db_settings = repo.get_all_settings()
        result: dict[str, object] = {}

        for key, schema in FINANCE_SETTINGS_SCHEMA.items():
            config_key = key.upper()
            cfg_val = app.config.get(config_key, schema.get("default", ""))
            if schema["type"] == "bool":
                cfg_default = _bool_to_01(cfg_val)
            else:
                cfg_default = str(cfg_val or "")

            value = db_settings.get(key, cfg_default)
            if schema.get("secret"):
                result[key] = ""
                result[f"{key}_set"] = bool(str(value).strip())
            else:
                result[key] = value

        return jsonify(result)

    @app.put("/api/finance/settings")
    @limiter.limit("10/minute")
    @require_finance_key
    def finance_update_settings():
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return jsonify({"error": "JSON inválido"}), 400

        errors: list[str] = []
        valid: dict[str, str] = {}

        for key, value in body.items():
            schema = FINANCE_SETTINGS_SCHEMA.get(key)
            if not schema:
                continue

            if schema.get("secret") and not str(value).strip():
                continue

            ok, normalized, msg = _validate_fin_setting(key, value)
            if ok:
                valid[key] = normalized
            else:
                errors.append(msg)

        if errors:
            return jsonify({"error": "; ".join(errors)}), 400
        if not valid:
            return jsonify({"error": "Nenhuma configuração válida enviada"}), 400

        repo.set_settings_bulk(valid)

        for key, value in valid.items():
            schema = FINANCE_SETTINGS_SCHEMA[key]
            config_key = key.upper()
            if schema["type"] == "int":
                app.config[config_key] = int(value)
            elif schema["type"] == "bool":
                app.config[config_key] = value == "1"
            else:
                app.config[config_key] = value

        _invalidate_financial_state_cache(include_market=True)

        return jsonify({"updated": list(valid.keys()), "count": len(valid)})

    @app.get("/api/finance/api-stats")
    @limiter.limit("30/minute")
    def finance_api_stats():
        try:
            def _resolve_brapi_policy() -> tuple[int, int, int, int]:
                raw_limit = app.config.get("BRAPI_MONTHLY_LIMIT")
                if raw_limit is None:
                    raw_limit = repo.get_setting("brapi_monthly_limit", "15000")
                try:
                    brapi_limit = max(100, min(500000, int(str(raw_limit).strip())))
                except Exception:
                    brapi_limit = 15000

                raw_reserve = app.config.get("BRAPI_RESERVE_PCT")
                if raw_reserve is None:
                    raw_reserve = repo.get_setting("brapi_reserve_pct", "15")
                try:
                    reserve_pct = max(0, min(50, int(str(raw_reserve).strip())))
                except Exception:
                    reserve_pct = 15

                raw_max_calls = app.config.get("BRAPI_MAX_CALLS_PER_REQUEST")
                if raw_max_calls is None:
                    raw_max_calls = repo.get_setting("brapi_max_calls_per_request", "2")
                try:
                    max_calls = max(0, min(200, int(str(raw_max_calls).strip())))
                except Exception:
                    max_calls = 2

                reserve_calls = int(math.ceil(brapi_limit * (reserve_pct / 100.0)))
                usable_limit = max(0, brapi_limit - reserve_calls)
                return brapi_limit, reserve_pct, reserve_calls, max_calls

            month_key = datetime.now(timezone.utc).strftime("%Y%m")
            usage_key = f"brapi_usage:{month_key}"
            brapi_usage = int(repo.get_setting(usage_key, "0") or 0)
            brapi_limit, reserve_pct, reserve_calls, max_calls = _resolve_brapi_policy()
            usable_limit = max(0, brapi_limit - reserve_calls)
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            payload = {
                "ok": True,
                "brapi_monthly": {
                    "month": month_key,
                    "usage": brapi_usage,
                    "limit": brapi_limit,
                    "reserve_pct": reserve_pct,
                    "reserve_calls": reserve_calls,
                    "usable_limit": usable_limit,
                    "remaining": max(0, brapi_limit - brapi_usage),
                    "remaining_usable": max(0, usable_limit - brapi_usage),
                    "per_request_cap": max_calls,
                    "degraded": brapi_usage >= usable_limit,
                },
                "daily_usage": {
                    "brapi": int(repo.get_setting(f"api_usage:{today}:market-data:brapi", "0") or 0),
                    "yahoo": int(repo.get_setting(f"api_usage:{today}:market-data:yahoo", "0") or 0),
                    "coingecko": int(repo.get_setting(f"api_usage:{today}:market-data:coingecko", "0") or 0),
                    "bcb": int(repo.get_setting(f"api_usage:{today}:benchmark:bcb", "0") or 0),
                },
                "provider_metrics": _provider_day_metrics(today),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            return jsonify(payload)
        except Exception as exc:
            logger.warning("finance api stats failed: %s", exc)
            return jsonify({"ok": False, "error": "Falha ao carregar estatísticas"}), 500

    @app.get("/api/finance/health")
    @limiter.limit("30/minute")
    def finance_health():
        try:
            now = datetime.now(timezone.utc)
            today = now.strftime("%Y-%m-%d")
            month_key = now.strftime("%Y%m")

            raw_limit = app.config.get("BRAPI_MONTHLY_LIMIT")
            if raw_limit is None:
                raw_limit = repo.get_setting("brapi_monthly_limit", "15000")
            try:
                brapi_limit = max(100, min(500000, int(str(raw_limit).strip())))
            except Exception:
                brapi_limit = 15000

            raw_reserve = app.config.get("BRAPI_RESERVE_PCT")
            if raw_reserve is None:
                raw_reserve = repo.get_setting("brapi_reserve_pct", "15")
            try:
                reserve_pct = max(0, min(50, int(str(raw_reserve).strip())))
            except Exception:
                reserve_pct = 15

            reserve_calls = int(math.ceil(brapi_limit * (reserve_pct / 100.0)))
            usable_limit = max(0, brapi_limit - reserve_calls)

            brapi_usage = int(repo.get_setting(f"brapi_usage:{month_key}", "0") or 0)
            brapi_remaining = max(0, brapi_limit - brapi_usage)
            brapi_degraded = brapi_usage >= usable_limit

            providers = _provider_day_metrics(today)

            market_cached = cache.get("finance:market") or {}
            market_quality = (market_cached.get("meta") or {}).get("quality") or {}
            stale_items = int(market_quality.get("stale_items") or 0)
            has_stale_data = bool(market_quality.get("has_stale_data"))

            provider_errors = []
            for provider in providers.values():
                total = int(provider.get("total") or 0)
                success_rate = provider.get("success_rate")
                if total >= 5 and success_rate is not None and float(success_rate) < 0.7:
                    provider_errors.append(provider.get("provider"))

            status = "ok"
            if brapi_degraded or has_stale_data or provider_errors:
                status = "degraded"

            return jsonify({
                "ok": True,
                "status": status,
                "timestamp": now.isoformat(),
                "checks": {
                    "brapi_quota": {
                        "status": "degraded" if brapi_degraded else "ok",
                        "month": month_key,
                        "usage": brapi_usage,
                        "limit": brapi_limit,
                        "remaining": brapi_remaining,
                        "reserve_pct": reserve_pct,
                        "reserve_calls": reserve_calls,
                        "usable_limit": usable_limit,
                        "remaining_usable": max(0, usable_limit - brapi_usage),
                    },
                    "market_quality": {
                        "status": "degraded" if has_stale_data else "ok",
                        "has_stale_data": has_stale_data,
                        "stale_items": stale_items,
                        "captured_at": market_quality.get("captured_at"),
                    },
                    "providers": {
                        "status": "degraded" if provider_errors else "ok",
                        "degraded_providers": provider_errors,
                        "metrics": providers,
                    },
                },
            })
        except Exception as exc:
            logger.warning("finance health failed: %s", exc)
            return jsonify({"ok": False, "error": "Falha ao carregar health"}), 500