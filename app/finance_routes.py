"""Financial dashboard routes."""

import csv
import io
import json
import logging
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from threading import Lock

import requests as http_requests
from flask import Flask, jsonify, render_template, request
from flask_limiter import Limiter

from .cache import get_cache
from .repository import Repository
from .security import require_finance_key, sanitize_text

_RETRY_EXCEPTIONS = (
    http_requests.exceptions.ConnectionError,
    http_requests.exceptions.Timeout,
    http_requests.exceptions.ChunkedEncodingError,
)


def _http_get_with_retry(
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: int = 10,
    max_retries: int = 2,
) -> http_requests.Response:
    """GET with exponential-backoff retry on transient network errors.

    Only retries on connection/timeout failures — never on 4xx/5xx responses.
    """
    delay = 0.5
    for attempt in range(max_retries + 1):
        try:
            return http_requests.get(
                url, params=params, headers=headers, timeout=timeout,
            )
        except _RETRY_EXCEPTIONS as exc:
            if attempt >= max_retries:
                raise
            logging.getLogger(__name__).debug(
                "Retry %d/%d for %s after error: %s",
                attempt + 1, max_retries, url, exc,
            )
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


def register_finance_routes(app: Flask, limiter: Limiter) -> None:
    logger = logging.getLogger(__name__)
    repo = Repository(app.config["DATABASE_TARGET"])
    cache = get_cache(app.config)
    app._finance_cache = cache  # exposed for tests

    FINANCE_CACHE_TTLS = {
        "summary": 60,
        "market": 300,
        "portfolio_history": 120,
        "asset_history": 120,
        "invested_history": 120,
        "performance": 90,
        "audit": 30,
        "allocation_targets": 120,
        "dividend_summary": 120,
        "passive_income_goal": 300,
        "dividend_ceiling": 300,
        "independence": 180,
        "benchmark": 600,
    }
    CLEANUP_CONFIRM_TOKEN = "CONFIRM_CLEANUP_DUPLICATES"
    CLEANUP_COOLDOWN_SECONDS = 600
    CLEANUP_IDEMPOTENCY_TTL = 3600

    def _invalidate_cache_prefixes(*prefixes: str) -> None:
        for prefix in prefixes:
            if not prefix:
                continue
            if hasattr(cache, "delete_prefix"):
                cache.delete_prefix(prefix)
            else:
                cache.delete(prefix)

    def _invalidate_financial_state_cache(
        *,
        include_market: bool = False,
        include_dividends: bool = False,
    ) -> None:
        prefixes = [
            "finance:summary",
            "finance:portfolio-history:",
            "finance:asset-history:",
            "finance:invested-history:",
            "finance:performance:",
            "finance:dividend-ceiling:",
            "finance:independence:",
        ]
        if include_dividends:
            prefixes.append("finance:dividend-summary")
        if include_market:
            prefixes.append("finance:market")
        _invalidate_cache_prefixes(*prefixes)

    # ── Page ────────────────────────────────────────────────

    def _finance_flags_payload() -> dict[str, bool]:
        defaults: dict[str, bool] = {
            "a11yEnhancements": True,
            "keyboardShortcuts": True,
            "sectionQuickNav": True,
            "featureFlagsUI": True,
            "perfTelemetry": True,
            "lazyRebalanceLoad": True,
            "secondaryPanelCache": True,
        }
        raw = app.config.get("FINANCE_FEATURE_FLAGS")
        if raw is None:
            return defaults

        parsed: dict | None = None
        if isinstance(raw, dict):
            parsed = raw
        elif isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = None

        if not parsed:
            return defaults

        merged = dict(defaults)
        for key in defaults:
            if key in parsed:
                merged[key] = bool(parsed[key])
        return merged

    @app.get("/finance")
    def finance_page():
        return render_template(
            "finance.html",
            finance_flags=_finance_flags_payload(),
        )

    @app.get("/finance/registros")
    def finance_records_page():
        return render_template("finance_records.html")

    # ── Summary ─────────────────────────────────────────────

    @app.get("/api/finance/summary")
    @limiter.limit("30/minute")
    def finance_summary():
        cached = cache.get("finance:summary")
        if cached:
            return jsonify(cached)
        summary = repo.get_fin_summary()
        currency = repo.list_currency_rates()
        summary["currency_rates"] = currency
        cache.set("finance:summary", summary, FINANCE_CACHE_TTLS["summary"])
        return jsonify(summary)

    # ── Finance Settings (keys & providers) ───────────────

    FINANCE_SETTINGS_SCHEMA: dict[str, dict] = {
        "brapi_token": {
            "type": "str", "max_len": 300, "default": "", "secret": True,
        },
        "brapi_monthly_limit": {
            "type": "int", "min": 100, "max": 500000, "default": "15000",
        },
        "brapi_max_calls_per_request": {
            "type": "int", "min": 0, "max": 200, "default": "2",
        },
        "brapi_reserve_pct": {
            "type": "int", "min": 0, "max": 50, "default": "15",
        },
        "finance_api_key": {
            "type": "str", "max_len": 300, "default": "", "secret": True,
        },
        "ai_local_enabled": {"type": "bool", "default": "1"},
        "ai_local_url": {
            "type": "url", "max_len": 300,
            "default": "http://llamacpp:8080",
        },
        "ai_local_model": {
            "type": "str", "max_len": 200,
            "default": "qwen2.5:7b-instruct",
        },
        "ai_local_timeout_seconds": {
            "type": "int", "min": 5, "max": 300, "default": "45",
        },
        "currency_api_url": {
            "type": "url", "max_len": 500,
            "default": "https://economia.awesomeapi.com.br/last/USD-BRL,EUR-BRL,BTC-BRL",
        },
        "currency_update_minutes": {
            "type": "int", "min": 1, "max": 1440, "default": "15",
        },
    }

    def _bool_to_01(value: object) -> str:
        if isinstance(value, bool):
            return "1" if value else "0"
        txt = str(value).strip().lower()
        return "1" if txt in ("1", "true", "yes", "on") else "0"

    def _validate_fin_setting(key: str, value: object) -> tuple[bool, str, str]:
        schema = FINANCE_SETTINGS_SCHEMA.get(key)
        if not schema:
            return False, "", f"Unknown setting: {key}"

        stype = schema["type"]
        raw = str(value).strip()

        if stype == "int":
            try:
                v = int(raw)
                if v < schema.get("min", -9999999) or v > schema.get("max", 9999999):
                    return False, "", f"{key}: valor fora do intervalo"
                return True, str(v), ""
            except ValueError:
                return False, "", f"{key}: deve ser número inteiro"

        if stype == "bool":
            if isinstance(value, bool):
                return True, "1" if value else "0", ""
            if raw.lower() in ("0", "1", "true", "false", "yes", "no", "on", "off"):
                return True, _bool_to_01(raw), ""
            return False, "", f"{key}: deve ser booleano"

        if stype == "url":
            if len(raw) > schema.get("max_len", 500):
                return False, "", f"{key}: URL muito longa"
            return True, raw, ""

        if stype == "str":
            if len(raw) > schema.get("max_len", 500):
                return False, "", f"{key}: texto muito longo"
            return True, raw, ""

        return True, raw, ""

    def _is_finite_number(value: object) -> bool:
        try:
            n = float(value)
        except (TypeError, ValueError):
            return False
        return math.isfinite(n)

    def _normalize_tags(value: object, *, max_items: int = 12) -> list[str]:
        items: list[str] = []
        if isinstance(value, list):
            items = [str(x) for x in value]
        elif isinstance(value, str):
            items = [x.strip() for x in value.split(",")]
        else:
            return []

        out: list[str] = []
        seen: set[str] = set()
        for raw in items:
            tag = sanitize_text(str(raw or "").strip().lower(), 30)
            if not tag or tag in seen:
                continue
            seen.add(tag)
            out.append(tag)
            if len(out) >= max_items:
                break
        return out

    def _track_api_provider_usage(provider: str, success: bool, endpoint: str = "") -> None:
        try:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            base_key = f"api_usage:{today}:{endpoint}:{provider}"
            total = int(repo.get_setting(base_key, "0") or 0)
            status_key = f"{base_key}:{'ok' if success else 'err'}"
            status = int(repo.get_setting(status_key, "0") or 0)
            repo.set_setting(base_key, str(total + 1))
            repo.set_setting(status_key, str(status + 1))
            cache.delete(f"finance:provider-metrics:{today}")
        except Exception:
            pass

    def _track_api_provider_latency(
        provider: str,
        endpoint: str,
        latency_ms: float,
    ) -> None:
        try:
            if not math.isfinite(float(latency_ms)):
                return
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            base_key = f"api_usage:{today}:{endpoint}:{provider}"
            sum_key = f"{base_key}:latency_sum_ms"
            count_key = f"{base_key}:latency_count"
            cur_sum = float(repo.get_setting(sum_key, "0") or 0)
            cur_count = int(repo.get_setting(count_key, "0") or 0)
            repo.set_setting(sum_key, f"{cur_sum + float(latency_ms):.3f}")
            repo.set_setting(count_key, str(cur_count + 1))
            cache.delete(f"finance:provider-metrics:{today}")
        except Exception:
            pass

    def _track_api_provider_fallback(provider: str, endpoint: str = "") -> None:
        try:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            base_key = f"api_usage:{today}:{endpoint}:{provider}"
            fallback_key = f"{base_key}:fallback"
            cur = int(repo.get_setting(fallback_key, "0") or 0)
            repo.set_setting(fallback_key, str(cur + 1))
            cache.delete(f"finance:provider-metrics:{today}")
        except Exception:
            pass

    def _provider_day_metrics(day_key: str) -> dict[str, dict]:
        cache_key = f"finance:provider-metrics:{day_key}"
        cached: dict[str, dict] | None = cache.get(cache_key)
        if cached is not None:
            return cached

        settings = repo.get_all_settings()
        prefix = f"api_usage:{day_key}:"
        providers: dict[str, dict] = {}

        for key, value in settings.items():
            if not key.startswith(prefix):
                continue
            parts = key.split(":")
            if len(parts) < 4:
                continue
            endpoint = str(parts[2] or "")
            provider = str(parts[3] or "")
            suffix = parts[4] if len(parts) >= 5 else ""
            if not endpoint or not provider:
                continue

            p = providers.setdefault(
                provider,
                {
                    "provider": provider,
                    "total": 0,
                    "ok": 0,
                    "err": 0,
                    "fallback": 0,
                    "latency_sum_ms": 0.0,
                    "latency_count": 0,
                    "endpoints": {},
                },
            )
            ep = p["endpoints"].setdefault(
                endpoint,
                {
                    "total": 0,
                    "ok": 0,
                    "err": 0,
                    "fallback": 0,
                    "latency_sum_ms": 0.0,
                    "latency_count": 0,
                },
            )

            if suffix == "ok":
                n = int(value or 0)
                p["ok"] += n
                ep["ok"] += n
            elif suffix == "err":
                n = int(value or 0)
                p["err"] += n
                ep["err"] += n
            elif suffix == "fallback":
                n = int(value or 0)
                p["fallback"] += n
                ep["fallback"] += n
            elif suffix == "latency_sum_ms":
                n = float(value or 0)
                p["latency_sum_ms"] += n
                ep["latency_sum_ms"] += n
            elif suffix == "latency_count":
                n = int(value or 0)
                p["latency_count"] += n
                ep["latency_count"] += n
            elif suffix == "":
                n = int(value or 0)
                p["total"] += n
                ep["total"] += n

        for provider_metrics in providers.values():
            total = int(provider_metrics.get("total") or 0)
            ok = int(provider_metrics.get("ok") or 0)
            fb = int(provider_metrics.get("fallback") or 0)
            lsum = float(provider_metrics.get("latency_sum_ms") or 0)
            lcount = int(provider_metrics.get("latency_count") or 0)
            provider_metrics["success_rate"] = round((ok / total), 4) if total > 0 else None
            provider_metrics["fallback_rate"] = round((fb / total), 4) if total > 0 else None
            provider_metrics["avg_latency_ms"] = round((lsum / lcount), 2) if lcount > 0 else None
            provider_metrics.pop("latency_sum_ms", None)

            for endpoint_metrics in provider_metrics["endpoints"].values():
                etotal = int(endpoint_metrics.get("total") or 0)
                eok = int(endpoint_metrics.get("ok") or 0)
                efb = int(endpoint_metrics.get("fallback") or 0)
                elsum = float(endpoint_metrics.get("latency_sum_ms") or 0)
                elcount = int(endpoint_metrics.get("latency_count") or 0)
                endpoint_metrics["success_rate"] = (
                    round((eok / etotal), 4)
                    if etotal > 0
                    else None
                )
                endpoint_metrics["fallback_rate"] = (
                    round((efb / etotal), 4)
                    if etotal > 0
                    else None
                )
                endpoint_metrics["avg_latency_ms"] = (
                    round((elsum / elcount), 2)
                    if elcount > 0
                    else None
                )
                endpoint_metrics.pop("latency_sum_ms", None)

        cache.set(cache_key, providers, 60)
        return providers

    def _audit(
        action: str,
        target_type: str,
        target_id: int | None,
        payload: dict | None = None,
    ) -> None:
        try:
            forwarded_for = str(
                request.headers.get("X-Forwarded-For", ""),
            ).split(",")[0].strip()
            meta = {
                "ip": forwarded_for or str(request.remote_addr or ""),
                "ua": str(request.user_agent.string or "")[:180],
                "path": str(request.path or ""),
                "method": str(request.method or ""),
            }
            merged_payload = dict(payload or {})
            merged_payload["_meta"] = meta
            repo.add_fin_audit_log(
                action,
                target_type,
                target_id,
                merged_payload,
            )
            _invalidate_cache_prefixes("finance:audit:")
        except Exception as exc:
            logger.warning("finance audit failed: %s", exc)

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

            # For secret fields: blank means keep current value
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

        # Apply immediately to app.config
        for key, value in valid.items():
            schema = FINANCE_SETTINGS_SCHEMA[key]
            config_key = key.upper()
            if schema["type"] == "int":
                app.config[config_key] = int(value)
            elif schema["type"] == "bool":
                app.config[config_key] = value == "1"
            else:
                app.config[config_key] = value

        # Invalidate caches affected by provider/config updates
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
                    raw_max_calls = repo.get_setting(
                        "brapi_max_calls_per_request",
                        "2",
                    )
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
            for p in providers.values():
                total = int(p.get("total") or 0)
                success_rate = p.get("success_rate")
                if total >= 5 and success_rate is not None and float(success_rate) < 0.7:
                    provider_errors.append(p.get("provider"))

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

    # ── Assets CRUD ─────────────────────────────────────────

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
        return jsonify({"ok": True, "id": asset_id}), 201

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
        return finance_asset_history_alt(asset_id)

    # ── Portfolio ───────────────────────────────────────────

    @app.get("/api/finance/portfolio")
    @limiter.limit("30/minute")
    def finance_portfolio():
        return jsonify(repo.get_fin_portfolio())

    # ── Transactions ────────────────────────────────────────

    @app.get("/api/finance/transactions")
    @limiter.limit("30/minute")
    def finance_list_transactions():
        asset_id = request.args.get("asset_id", type=int)
        limit = min(500, max(1, int(request.args.get("limit", "100"))))
        return jsonify(repo.list_fin_transactions(asset_id, limit))

    @app.post("/api/finance/transactions")
    @limiter.limit("15/minute")
    @require_finance_key
    def finance_add_transaction():
        body = request.get_json(silent=True)
        if not body:
            return jsonify({"error": "JSON inválido"}), 400
        required = ["asset_id", "quantity", "price"]
        missing = [k for k in required if k not in body]
        if missing:
            return jsonify({"error": f"Campos: {', '.join(missing)}"}), 400
        try:
            qty = float(body["quantity"])
            price = float(body["price"])
            fees = float(body.get("fees", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "Valores numéricos inválidos"}), 400
        if not all(_is_finite_number(v) for v in (qty, price, fees)):
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

        # Update portfolio automatically
        _recalc_portfolio(repo, data["asset_id"])
        _audit("add", "transaction", tx_id, {"asset_id": data["asset_id"], "tx_type": tx_type})
        _invalidate_financial_state_cache()
        return jsonify({"ok": True, "id": tx_id}), 201

    @app.delete("/api/finance/transactions/<int:tx_id>")
    @limiter.limit("15/minute")
    @require_finance_key
    def finance_delete_transaction(tx_id: int):
        # Get asset_id before deleting
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
        data: dict = {}
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
        # Recompute total if qty or price changed
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
            tx_ids = sorted({int(x) for x in tx_ids_raw if int(x) > 0})
        except (TypeError, ValueError):
            return jsonify({"error": "tx_ids inválido"}), 400
        updates = body.get("updates") or {}
        if not isinstance(updates, dict) or not updates:
            return jsonify({"error": "updates obrigatório"}), 400

        data: dict = {}
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
                by_id = {int(t["id"]): t for t in txs}
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
        by_id = {int(t["id"]): t for t in txs}
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

    @app.post("/api/finance/maintenance/cleanup-duplicates")
    @limiter.limit("2/day")
    @require_finance_key
    def finance_cleanup_duplicate_transactions():
        confirm_token = str(request.headers.get("X-Cleanup-Confirm", "")).strip()
        if confirm_token != CLEANUP_CONFIRM_TOKEN:
            return jsonify({
                "error": "Confirmação obrigatória para limpeza.",
                "required_header": "X-Cleanup-Confirm",
                "required_value": CLEANUP_CONFIRM_TOKEN,
            }), 400

        idem_key = str(request.headers.get("X-Idempotency-Key", "")).strip()
        if not idem_key:
            return jsonify({
                "error": "Header X-Idempotency-Key é obrigatório.",
            }), 400

        idem_cache_key = f"finance:cleanup:idem:{idem_key}"
        cached_result = cache.get(idem_cache_key)
        if cached_result:
            return jsonify({"ok": True, "idempotent_replay": True, **cached_result})

        now_ts = int(datetime.now(timezone.utc).timestamp())
        cooldown_key = "finance:cleanup:last_run_ts"
        last_run = cache.get(cooldown_key) or {}
        last_ts = int(last_run.get("ts", 0) or 0)
        if last_ts and (now_ts - last_ts) < CLEANUP_COOLDOWN_SECONDS:
            retry_after = CLEANUP_COOLDOWN_SECONDS - (now_ts - last_ts)
            return jsonify({
                "error": "Cleanup em cooldown. Tente novamente depois.",
                "retry_after_seconds": retry_after,
            }), 429

        tx_payload = repo.cleanup_duplicate_fin_transactions()
        div_payload = repo.cleanup_duplicate_fin_dividends()
        touched_asset_ids = [
            int(aid) for aid in tx_payload.pop("touched_asset_ids", [])
        ]
        for asset_id in touched_asset_ids:
            _recalc_portfolio(repo, asset_id)
        _invalidate_financial_state_cache(
            include_market=True,
            include_dividends=True,
        )
        _audit(
            "cleanup",
            "duplicates",
            None,
            {
                "tx_deleted": tx_payload.get("deleted", 0),
                "div_deleted": div_payload.get("deleted", 0),
                "assets": len(touched_asset_ids),
                "idempotency_key": idem_key,
            },
        )
        response_payload = {
            "ok": True,
            "transactions": tx_payload,
            "dividends": div_payload,
        }
        cache.set(idem_cache_key, response_payload, CLEANUP_IDEMPOTENCY_TTL)
        cache.set(cooldown_key, {"ts": now_ts}, CLEANUP_COOLDOWN_SECONDS)
        return jsonify(response_payload)

    @app.post("/api/finance/maintenance/cleanup-stale")
    @limiter.limit("2/day")
    @require_finance_key
    def finance_cleanup_stale_data():
        confirm_token = str(request.headers.get("X-Cleanup-Confirm", "")).strip()
        if confirm_token != CLEANUP_CONFIRM_TOKEN:
            return jsonify({
                "error": "Confirmação obrigatória para limpeza.",
                "required_header": "X-Cleanup-Confirm",
                "required_value": CLEANUP_CONFIRM_TOKEN,
            }), 400
        keep_days = min(365, max(7, int(request.args.get("keep_days", "90"))))
        cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).strftime("%Y-%m-%d")
        settings = repo.get_all_settings()
        stale_keys = []
        for key in settings.keys():
            if not key.startswith("api_usage:"):
                continue
            parts = key.split(":")
            if len(parts) >= 2 and parts[1] < cutoff:
                stale_keys.append(key)
        deleted = 0
        for key in stale_keys:
            if repo.delete_setting(key):
                deleted += 1
        _audit("cleanup", "stale_api_usage", None, {"deleted": deleted, "keep_days": keep_days})
        return jsonify({"ok": True, "deleted": deleted, "keep_days": keep_days})

    @app.post("/api/finance/maintenance/migrate-asset-types")
    @limiter.limit("2/day")
    @require_finance_key
    def finance_migrate_asset_types():
        confirm_token = str(request.headers.get("X-Cleanup-Confirm", "")).strip()
        if confirm_token != CLEANUP_CONFIRM_TOKEN:
            return jsonify({
                "error": "Confirmação obrigatória para migração.",
                "required_header": "X-Cleanup-Confirm",
                "required_value": CLEANUP_CONFIRM_TOKEN,
            }), 400
        payload = repo.normalize_fin_asset_types()
        _invalidate_financial_state_cache(include_market=True)
        _audit("maintenance", "migrate_asset_types", None, payload)
        return jsonify({"ok": True, **payload})

    @app.get("/api/finance/maintenance/cleanup-duplicates")
    def finance_cleanup_duplicate_transactions_help():
        return jsonify({
            "ok": True,
            "message": "Use POST para executar a limpeza de duplicatas.",
            "method": "POST",
            "path": "/api/finance/maintenance/cleanup-duplicates",
            "required_headers": {
                "X-Cleanup-Confirm": CLEANUP_CONFIRM_TOKEN,
                "X-Idempotency-Key": "<valor-unico>",
            },
            "cooldown_seconds": CLEANUP_COOLDOWN_SECONDS,
        })

    # ── Watchlist ───────────────────────────────────────────

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
        return jsonify({"ok": True, "id": wl_id}), 201

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
        data: dict = {}
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
        return jsonify({"ok": True})

    # ── Goals ───────────────────────────────────────────────

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
            "category": sanitize_text(
                str(body.get("category", "savings")), 30,
            ),
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
        data = {}
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

    # ── Cashflow (gains / expenses) ────────────────────────

    def _build_simple_pdf(lines: list[str]) -> bytes:
        """Generate a small single-page PDF without external dependencies."""

        def _esc(text: str) -> str:
            return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

        safe_lines = [sanitize_text(str(line or ""), 240) for line in lines[:80]]
        content_lines = ["BT", "/F1 10 Tf", "40 800 Td", "12 TL"]
        for idx, line in enumerate(safe_lines):
            if idx > 0:
                content_lines.append("T*")
            content_lines.append(f"({_esc(line)}) Tj")
        content_lines.append("ET")
        stream = "\n".join(content_lines).encode("latin-1", errors="replace")

        objs: list[bytes] = []
        objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
        objs.append(b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>")
        objs.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        )
        objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        objs.append(
            b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )

        out = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for i, obj in enumerate(objs, start=1):
            offsets.append(len(out))
            out.extend(f"{i} 0 obj\n".encode("ascii"))
            out.extend(obj)
            out.extend(b"\nendobj\n")

        xref_pos = len(out)
        out.extend(f"xref\n0 {len(objs) + 1}\n".encode("ascii"))
        out.extend(b"0000000000 65535 f \n")
        for off in offsets[1:]:
            out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
        out.extend(
            (
                f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
                f"startxref\n{xref_pos}\n%%EOF"
            ).encode("ascii")
        )
        return bytes(out)

    @app.get("/api/finance/cashflow")
    @limiter.limit("30/minute")
    def finance_list_cashflow():
        month = sanitize_text(str(request.args.get("month", "")), 7).strip()
        entry_type = sanitize_text(str(request.args.get("type", "")), 12).strip().lower()
        payment_status = sanitize_text(str(request.args.get("status", "")), 12).strip().lower()
        cost_center = sanitize_text(str(request.args.get("cost_center", "")), 60).strip()
        subcategory = sanitize_text(str(request.args.get("subcategory", "")), 60).strip()
        tag = sanitize_text(str(request.args.get("tag", "")), 30).strip().lower()
        q = sanitize_text(str(request.args.get("q", "")), 120).strip()
        limit = int(request.args.get("limit", "500"))

        if month and not re.match(r"^\d{4}-\d{2}$", month):
            return jsonify({"error": "month inválido (use YYYY-MM)"}), 400
        if entry_type and entry_type not in ("income", "expense"):
            return jsonify({"error": "type inválido (income|expense)"}), 400
        if payment_status and payment_status not in ("pending", "paid"):
            return jsonify({"error": "status inválido (pending|paid)"}), 400

        payload = repo.list_fin_cashflow_entries(
            month=month or None,
            entry_type=entry_type or None,
            payment_status=payment_status or None,
            q=q or None,
            cost_center=cost_center or None,
            subcategory=subcategory or None,
            tag=tag or None,
            limit=max(1, min(2000, limit)),
        )
        return jsonify(payload)

    @app.get("/api/finance/cashflow/summary")
    @limiter.limit("30/minute")
    def finance_cashflow_summary():
        months = int(request.args.get("months", "6"))
        payload = repo.get_fin_cashflow_summary(months=max(1, min(24, months)))
        return jsonify(payload)

    @app.get("/api/finance/cashflow/alerts")
    @limiter.limit("30/minute")
    def finance_cashflow_alerts():
        days = min(60, max(1, int(request.args.get("days", "7"))))
        today = datetime.now(timezone.utc).date()

        rows = repo.list_fin_cashflow_entries(
            entry_type="expense",
            payment_status="pending",
            limit=5000,
        )

        due_items: list[dict] = []
        for row in rows:
            entry_date = str(row.get("entry_date") or "")[:10]
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", entry_date):
                continue
            try:
                due_date = datetime.strptime(entry_date, "%Y-%m-%d").date()
            except ValueError:
                continue

            days_to_due = (due_date - today).days
            if days_to_due < 0:
                severity = "overdue"
            elif days_to_due <= days:
                severity = "due_soon"
            else:
                continue

            due_items.append(
                {
                    "id": int(row.get("id") or 0),
                    "entry_date": entry_date,
                    "days_to_due": int(days_to_due),
                    "severity": severity,
                    "amount": round(float(row.get("amount") or 0), 2),
                    "category": str(row.get("category") or ""),
                    "description": str(row.get("description") or ""),
                },
            )

        severity_rank = {"overdue": 0, "due_soon": 1}
        due_items.sort(
            key=lambda item: (
                severity_rank.get(str(item.get("severity") or ""), 9),
                str(item.get("entry_date") or ""),
            ),
        )

        overdue_count = len([i for i in due_items if i.get("severity") == "overdue"])
        due_soon_count = len([i for i in due_items if i.get("severity") == "due_soon"])
        return jsonify(
            {
                "days_window": days,
                "counts": {
                    "overdue": overdue_count,
                    "due_soon": due_soon_count,
                    "total": len(due_items),
                },
                "items": due_items,
            },
        )

    @app.get("/api/finance/cashflow/audit")
    @limiter.limit("20/minute")
    @require_finance_key
    def finance_cashflow_audit_logs():
        limit = min(300, max(1, int(request.args.get("limit", "100"))))
        entry_id = request.args.get("entry_id", type=int)
        payload = repo.list_fin_audit_logs(limit)
        payload = [
            row
            for row in payload
            if str(row.get("target_type") or "").lower() == "cashflow"
        ]
        if entry_id is not None:
            payload = [
                row for row in payload if int(row.get("target_id") or 0) == int(entry_id)
            ]
        return jsonify(payload)

    @app.get("/api/finance/cashflow/analytics")
    @limiter.limit("30/minute")
    def finance_cashflow_analytics():
        month = sanitize_text(str(request.args.get("month", "")), 7).strip()
        if month and not re.match(r"^\d{4}-\d{2}$", month):
            return jsonify({"error": "month inválido (use YYYY-MM)"}), 400
        payload = repo.get_fin_cashflow_analytics(month=month or None)
        return jsonify(payload)

    @app.get("/api/finance/cashflow/budget")
    @limiter.limit("30/minute")
    def finance_cashflow_budget_get():
        month = sanitize_text(str(request.args.get("month", "")), 7).strip()
        if not month:
            month = datetime.now(timezone.utc).strftime("%Y-%m")
        if not re.match(r"^\d{4}-\d{2}$", month):
            return jsonify({"error": "month inválido (use YYYY-MM)"}), 400
        return jsonify({
            "month": month,
            "budget": repo.get_fin_cashflow_budget(month),
        })

    @app.put("/api/finance/cashflow/budget")
    @limiter.limit("15/minute")
    @require_finance_key
    def finance_cashflow_budget_put():
        body = request.get_json(silent=True) or {}
        month = sanitize_text(str(body.get("month", "")), 7).strip()
        if not month:
            month = datetime.now(timezone.utc).strftime("%Y-%m")
        if not re.match(r"^\d{4}-\d{2}$", month):
            return jsonify({"error": "month inválido (use YYYY-MM)"}), 400

        raw_budget = body.get("budget")
        if not isinstance(raw_budget, dict):
            return jsonify({"error": "budget deve ser um objeto {categoria: valor}"}), 400

        safe_budget: dict[str, float] = {}
        for k, v in raw_budget.items():
            category = sanitize_text(str(k or ""), 60).strip()
            if not category:
                continue
            try:
                amount = float(v)
            except (TypeError, ValueError):
                continue
            if not _is_finite_number(amount) or amount < 0:
                continue
            safe_budget[category] = round(amount, 2)

        repo.set_fin_cashflow_budget(month, safe_budget)
        _audit(
            "update",
            "cashflow_budget",
            None,
            {"month": month, "categories": sorted(list(safe_budget.keys()))},
        )
        return jsonify({"ok": True, "month": month, "budget": safe_budget})

    @app.post("/api/finance/cashflow/budget/template")
    @limiter.limit("10/minute")
    @require_finance_key
    def finance_cashflow_budget_template():
        """Aplica metodologia de orçamento pessoal (50/30/20, envelope, base-zero)."""
        body = request.get_json(silent=True) or {}
        method = sanitize_text(str(body.get("method", "50_30_20")), 20).strip()
        month = sanitize_text(str(body.get("month", "")), 7).strip()
        if not month:
            month = datetime.now(timezone.utc).strftime("%Y-%m")
        if not re.match(r"^\d{4}-\d{2}$", month):
            return jsonify({"error": "month inválido (use YYYY-MM)"}), 400
        try:
            income = float(body.get("income", 0))
        except (TypeError, ValueError):
            income = 0.0
        if not _is_finite_number(income) or income <= 0:
            return jsonify({"error": "income deve ser um valor positivo"}), 400
        apply = bool(body.get("apply", False))

        VALID_METHODS = {"50_30_20", "envelope", "zero_based"}
        if method not in VALID_METHODS:
            return jsonify({"error": f"method inválido. Use: {', '.join(sorted(VALID_METHODS))}"}), 400

        # Category name → (group, percentage of income)
        TEMPLATES: dict[str, dict] = {
            "50_30_20": {
                "label": "50/30/20 — Necessidades • Desejos • Poupança",
                "description": (
                    "50% da renda líquida para necessidades básicas, "
                    "30% para desejos pessoais e 20% para poupança/investimentos."
                ),
                "groups": {"Necessidades": 0.50, "Desejos": 0.30, "Poupança": 0.20},
                "categories": {
                    "Moradia": 0.25, "Alimentação": 0.10, "Transporte": 0.08,
                    "Saúde": 0.05, "Contas": 0.02,
                    "Restaurante": 0.08, "Lazer": 0.08, "Compras": 0.07,
                    "Assinaturas": 0.04, "Viagem": 0.03,
                    "Investimentos": 0.15, "Reserva": 0.05,
                },
            },
            "envelope": {
                "label": "Orçamento por Envelopes",
                "description": (
                    "Aloque valores fixos para cada 'envelope' (categoria) "
                    "até esgotar o total da renda disponível."
                ),
                "groups": {"Total": 1.0},
                "categories": {
                    "Moradia": 0.28, "Alimentação": 0.12, "Transporte": 0.10,
                    "Saúde": 0.08, "Lazer": 0.10, "Restaurante": 0.08,
                    "Compras": 0.07, "Assinaturas": 0.05, "Investimentos": 0.12,
                },
            },
            "zero_based": {
                "label": "Orçamento Base Zero",
                "description": (
                    "Cada real da renda é alocado explicitamente — "
                    "receita menos todas as despesas e investimentos deve ser R$0."
                ),
                "groups": {"Total": 1.0},
                "categories": {
                    "Moradia": 0.25, "Alimentação": 0.10, "Transporte": 0.08,
                    "Saúde": 0.05, "Contas": 0.03, "Restaurante": 0.07,
                    "Lazer": 0.07, "Compras": 0.06, "Assinaturas": 0.04,
                    "Viagem": 0.03, "Investimentos": 0.15, "Reserva": 0.04,
                    "Outros": 0.03,
                },
            },
        }

        tmpl = TEMPLATES[method]
        budget: dict[str, float] = {
            cat: round(income * pct, 2)
            for cat, pct in tmpl["categories"].items()
        }
        groups: dict[str, float] = {
            g: round(income * pct, 2)
            for g, pct in tmpl["groups"].items()
        }

        if apply:
            repo.set_fin_cashflow_budget(month, budget)
            _audit("update", "cashflow_budget", None, {
                "method": method, "month": month,
                "income": income, "categories": sorted(budget.keys()),
            })

        return jsonify({
            "ok": True,
            "method": method,
            "label": tmpl["label"],
            "description": tmpl["description"],
            "income": income,
            "month": month,
            "applied": apply,
            "budget": budget,
            "groups": groups,
        })

    @app.get("/api/finance/cashflow/budget/check")
    @limiter.limit("60/minute")
    def finance_cashflow_budget_check():
        """Verifica se um gasto ultrapassaria o limite orçado para a categoria."""
        category = sanitize_text(str(request.args.get("category", "")), 60).strip()
        month = sanitize_text(str(request.args.get("month", "")), 7).strip()
        if not month:
            month = datetime.now(timezone.utc).strftime("%Y-%m")
        if not re.match(r"^\d{4}-\d{2}$", month):
            return jsonify({"error": "month inválido (use YYYY-MM)"}), 400
        if not category:
            return jsonify({"error": "category obrigatória"}), 400
        try:
            amount = float(request.args.get("amount", 0))
        except (TypeError, ValueError):
            amount = 0.0
        if not _is_finite_number(amount) or amount < 0:
            amount = 0.0

        budget = repo.get_fin_cashflow_budget(month)
        limit = budget.get(category)
        if limit is None:
            return jsonify({
                "category": category, "month": month,
                "has_budget": False, "limit": None,
                "spent": 0, "remaining": None, "over_budget": False,
            })

        analytics = repo.get_fin_cashflow_analytics(month=month)
        expense_cats = analytics.get("categories", {}).get("expense", [])
        spent = next(
            (float(r["amount"]) for r in expense_cats if r["category"] == category),
            0.0,
        )
        would_be = spent + amount
        return jsonify({
            "category": category,
            "month": month,
            "has_budget": True,
            "limit": round(limit, 2),
            "spent": round(spent, 2),
            "would_be_spent": round(would_be, 2),
            "remaining": round(limit - spent, 2),
            "over_budget": would_be > limit,
            "usage_pct": round(would_be / limit * 100 if limit > 0 else 0, 2),
        })

    @app.get("/api/finance/cashflow/budget/alerts")
    @limiter.limit("30/minute")
    def finance_cashflow_budget_alerts():
        month = sanitize_text(str(request.args.get("month", "")), 7).strip()
        if not month:
            month = datetime.now(timezone.utc).strftime("%Y-%m")
        if not re.match(r"^\d{4}-\d{2}$", month):
            return jsonify({"error": "month inválido (use YYYY-MM)"}), 400
        try:
            threshold = float(request.args.get("threshold", 80))
        except (TypeError, ValueError):
            threshold = 80.0
        threshold = max(0.0, min(200.0, threshold))

        analytics = repo.get_fin_cashflow_analytics(month=month)
        budget_items = analytics.get("budget", {}).get("items", [])
        alerts = []
        for item in budget_items:
            usage = float(item.get("usage_pct") or 0)
            if item.get("over_budget"):
                status = "over"
            elif usage >= threshold:
                status = "warning"
            else:
                status = "ok"
            alerts.append({
                "category": item["category"],
                "limit": item["limit"],
                "spent": item["spent"],
                "remaining": item["remaining"],
                "usage_pct": item["usage_pct"],
                "status": status,
            })
        alerts_only = [a for a in alerts if a["status"] != "ok"]
        return jsonify({
            "month": month,
            "threshold": threshold,
            "alerts": alerts_only,
            "all": alerts,
        })

    @app.get("/api/finance/cashflow/kpis")
    @limiter.limit("30/minute")
    def finance_cashflow_kpis():
        """KPIs avançados: savings rate, burn rate, runway."""
        month = sanitize_text(str(request.args.get("month", "")), 7).strip()
        if not month:
            month = datetime.now(timezone.utc).strftime("%Y-%m")
        if not re.match(r"^\d{4}-\d{2}$", month):
            return jsonify({"error": "month inválido (use YYYY-MM)"}), 400

        analytics = repo.get_fin_cashflow_analytics(month=month)
        totals = analytics.get("totals", {})
        income = float(totals.get("income") or 0)
        expense = float(totals.get("expense") or 0)
        balance = income - expense
        savings_rate_pct = round((balance / income * 100) if income > 0 else 0, 2)

        # burn rate = avg monthly expense across last 3 months
        year_n, month_n = int(month[:4]), int(month[5:7])
        burn_samples = []
        for i in range(1, 4):
            m = month_n - i
            y = year_n
            while m <= 0:
                m += 12
                y -= 1
            prev_key = f"{y:04d}-{m:02d}"
            prev = repo.get_fin_cashflow_analytics(month=prev_key)
            prev_exp = float(prev.get("totals", {}).get("expense") or 0)
            if prev_exp > 0:
                burn_samples.append(prev_exp)

        if burn_samples:
            burn_rate = round(sum(burn_samples) / len(burn_samples), 2)
        else:
            burn_rate = round(expense, 2)

        # runway: how many months current savings covers at burn rate
        total_balance_all = sum(
            float(r.get("amount") or 0) * (1 if str(r.get("entry_type") or "") == "income" else -1)
            for r in repo.list_fin_cashflow_entries(limit=50000)
        )
        runway_months = round(total_balance_all / burn_rate, 1) if burn_rate > 0 else None

        proj = analytics.get("projection", {})
        return jsonify({
            "month": month,
            "savings_rate_pct": savings_rate_pct,
            "income": round(income, 2),
            "expense": round(expense, 2),
            "balance": round(balance, 2),
            "burn_rate": burn_rate,
            "runway_months": runway_months,
            "projected_expense": proj.get("projected_expense"),
            "projected_income": proj.get("projected_income"),
        })

    @app.post("/api/finance/cashflow/auto-classify")
    @limiter.limit("20/minute")
    @require_finance_key
    def finance_cashflow_auto_classify():
        """Auto-classify unclassified or pending entries using keyword rules."""
        body = request.get_json(silent=True) or {}
        month = sanitize_text(str(body.get("month", "")), 7).strip()
        if not month:
            month = datetime.now(timezone.utc).strftime("%Y-%m")
        if not re.match(r"^\d{4}-\d{2}$", month):
            return jsonify({"error": "month inválido (use YYYY-MM)"}), 400

        # rules stored as app_settings JSON: [{"keyword": "...", "category": "..."}]
        raw_rules = repo.get_setting("cashflow_classify_rules") or "[]"
        try:
            rules: list[dict] = json.loads(raw_rules) if isinstance(raw_rules, str) else raw_rules
        except (json.JSONDecodeError, TypeError):
            rules = []

        entries = repo.list_fin_cashflow_entries(month=month, limit=5000)
        updated = 0
        for entry in entries:
            cat = str(entry.get("category") or "").strip()
            if cat and cat.lower() not in ("", "sem categoria", "outros"):
                continue
            desc = str(entry.get("description") or "").lower()
            for rule in rules:
                kw = str(rule.get("keyword") or "").lower().strip()
                new_cat = sanitize_text(str(rule.get("category") or ""), 60).strip()
                if kw and new_cat and kw in desc:
                    repo.update_fin_cashflow_entry(entry["id"], {"category": new_cat})
                    updated += 1
                    break

        _audit("update", "cashflow_auto_classify", None, {"month": month, "updated": updated})
        return jsonify({"ok": True, "month": month, "updated": updated})

    @app.get("/api/finance/cashflow/classify-rules")
    @limiter.limit("30/minute")
    def finance_cashflow_classify_rules_get():
        raw = repo.get_setting("cashflow_classify_rules") or "[]"
        try:
            rules = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            rules = []
        return jsonify({"rules": rules})

    @app.put("/api/finance/cashflow/classify-rules")
    @limiter.limit("15/minute")
    @require_finance_key
    def finance_cashflow_classify_rules_put():
        body = request.get_json(silent=True) or {}
        raw_rules = body.get("rules", [])
        if not isinstance(raw_rules, list):
            return jsonify({"error": "rules deve ser uma lista"}), 400
        safe_rules = []
        for r in raw_rules:
            kw = sanitize_text(str(r.get("keyword") or ""), 100).strip().lower()
            cat = sanitize_text(str(r.get("category") or ""), 60).strip()
            if kw and cat:
                safe_rules.append({"keyword": kw, "category": cat})
        repo.set_setting("cashflow_classify_rules", json.dumps(safe_rules))
        _audit("update", "cashflow_classify_rules", None, {"count": len(safe_rules)})
        return jsonify({"ok": True, "rules": safe_rules})

    @app.post("/api/finance/cashflow/scenario")
    @limiter.limit("20/minute")
    def finance_cashflow_scenario():
        """Simula o impacto de reduzir gastos em categorias."""
        body = request.get_json(silent=True) or {}
        month = sanitize_text(str(body.get("month", "")), 7).strip()
        if not month:
            month = datetime.now(timezone.utc).strftime("%Y-%m")
        if not re.match(r"^\d{4}-\d{2}$", month):
            return jsonify({"error": "month inválido (use YYYY-MM)"}), 400

        # adjustments: [{"category": "...", "reduction_pct": 20}]
        raw_adj = body.get("adjustments", [])
        if not isinstance(raw_adj, list):
            return jsonify({"error": "adjustments deve ser uma lista"}), 400

        adjustments: dict[str, float] = {}
        for adj in raw_adj:
            cat = sanitize_text(str(adj.get("category") or ""), 60).strip()
            try:
                pct = float(adj.get("reduction_pct") or 0)
            except (TypeError, ValueError):
                pct = 0.0
            pct = max(-100.0, min(100.0, pct))
            if cat:
                adjustments[cat] = pct

        analytics = repo.get_fin_cashflow_analytics(month=month)
        totals = analytics.get("totals", {})
        current_income = float(totals.get("income") or 0)
        current_expense = float(totals.get("expense") or 0)
        expense_cats = {
            c["category"]: float(c["amount"])
            for c in analytics.get("categories", {}).get("expense", [])
        }

        simulated_expense = 0.0
        scenario_detail = []
        for cat, amount in expense_cats.items():
            reduction_pct = adjustments.get(cat, 0.0)
            simulated = amount * (1 - reduction_pct / 100.0)
            simulated = max(0.0, simulated)
            simulated_expense += simulated
            scenario_detail.append({
                "category": cat,
                "current": round(amount, 2),
                "simulated": round(simulated, 2),
                "saving": round(amount - simulated, 2),
                "reduction_pct": round(reduction_pct, 2),
            })

        simulated_balance = current_income - simulated_expense
        current_balance = current_income - current_expense
        extra_savings = simulated_balance - current_balance
        monthly_saving = round(extra_savings, 2)
        yearly_saving = round(extra_savings * 12, 2)

        return jsonify({
            "month": month,
            "current": {
                "income": round(current_income, 2),
                "expense": round(current_expense, 2),
                "balance": round(current_balance, 2),
            },
            "simulated": {
                "expense": round(simulated_expense, 2),
                "balance": round(simulated_balance, 2),
            },
            "impact": {
                "monthly_saving": monthly_saving,
                "yearly_saving": yearly_saving,
            },
            "detail": scenario_detail,
        })

    @app.post("/api/finance/cashflow/import")
    @limiter.limit("10/minute")
    @require_finance_key
    def finance_cashflow_import():
        """Importa lançamentos de CSV ou OFX (arquivo enviado)."""
        month = sanitize_text(str(request.args.get("month", "")), 7).strip()
        if not month:
            month = datetime.now(timezone.utc).strftime("%Y-%m")
        if not re.match(r"^\d{4}-\d{2}$", month):
            return jsonify({"error": "month inválido (use YYYY-MM)"}), 400

        # force=true skips duplicate detection and inserts everything
        force = str(request.args.get("force", "0")).strip().lower() in ("1", "true")

        if "file" not in request.files:
            return jsonify({"error": "Nenhum arquivo enviado (campo 'file')"}), 400

        f = request.files["file"]
        filename = (f.filename or "").lower()
        raw_bytes = f.read(2 * 1024 * 1024)  # max 2 MB

        # Pre-load existing entries for smart duplicate detection
        existing_entries = repo.list_fin_cashflow_entries(month=month, limit=5000) if not force else []

        def _find_potential_duplicate(
            entry_type: str,
            amount: float,
            entry_date: str,
            description: str,
        ) -> dict | None:
            """Return the first existing entry that looks like a duplicate."""
            from datetime import datetime as _dt
            try:
                target_dt = _dt.strptime(entry_date, "%Y-%m-%d")
            except ValueError:
                return None

            for ex in existing_entries:
                ex_type = str(ex.get("entry_type") or "").lower()
                ex_amount = round(float(ex.get("amount") or 0), 2)
                ex_date_str = str(ex.get("entry_date") or "")[:10]
                if ex_type != entry_type or abs(ex_amount - round(amount, 2)) > 0.01:
                    continue
                try:
                    ex_dt = _dt.strptime(ex_date_str, "%Y-%m-%d")
                    if abs((target_dt - ex_dt).days) <= 3:
                        return {"id": ex.get("id"), "entry_date": ex_date_str,
                                "description": ex.get("description"), "amount": ex_amount}
                except ValueError:
                    continue
            return None

        candidates: list[dict] = []
        errors = []

        if filename.endswith(".csv"):
            try:
                text = raw_bytes.decode("utf-8", errors="replace")
                reader = csv.DictReader(io.StringIO(text))
                for i, row in enumerate(reader):
                    try:
                        entry_date = sanitize_text(str(row.get("date") or row.get("data") or ""), 10).strip()
                        if not re.match(r"^\d{4}-\d{2}-\d{2}$", entry_date):
                            raise ValueError(f"data inválida: {entry_date}")
                        raw_amount = str(row.get("amount") or row.get("valor") or "0").replace(",", ".")
                        amount = round(float(raw_amount), 2)
                        if amount <= 0:
                            raise ValueError("amount deve ser positivo")
                        entry_type_raw = str(row.get("type") or row.get("tipo") or "expense").strip().lower()
                        entry_type = entry_type_raw if entry_type_raw in ("income", "expense") else "expense"
                        category = sanitize_text(str(row.get("category") or row.get("categoria") or "Importado"), 60).strip()
                        description = sanitize_text(str(row.get("description") or row.get("descricao") or ""), 200).strip()
                        dup = _find_potential_duplicate(entry_type, amount, entry_date, description)
                        candidates.append({
                            "entry_type": entry_type, "amount": amount,
                            "category": category, "description": description,
                            "entry_date": entry_date, "notes": "Importado via CSV",
                            "_dup": dup,
                        })
                    except (ValueError, KeyError, TypeError) as exc:
                        errors.append({"row": i + 2, "error": str(exc)})
            except Exception as exc:
                return jsonify({"error": f"Erro ao processar CSV: {exc}"}), 400

        elif filename.endswith(".ofx"):
            try:
                text = raw_bytes.decode("utf-8", errors="replace")
                transactions = re.findall(r"<STMTTRN>(.*?)</STMTTRN>", text, re.DOTALL | re.IGNORECASE)
                for i, block in enumerate(transactions):
                    try:
                        def _ofx_val(tag: str) -> str:
                            m = re.search(rf"<{tag}>\s*([^\n<]+)", block, re.IGNORECASE)
                            return m.group(1).strip() if m else ""

                        raw_amt = _ofx_val("TRNAMT").replace(",", ".")
                        amount = float(raw_amt)
                        entry_type = "income" if amount >= 0 else "expense"
                        amount = round(abs(amount), 2)
                        if amount == 0:
                            continue
                        raw_date = _ofx_val("DTPOSTED")[:8]
                        if len(raw_date) == 8:
                            entry_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
                        else:
                            raise ValueError(f"DTPOSTED inválido: {raw_date}")
                        description = sanitize_text(_ofx_val("MEMO") or _ofx_val("NAME") or "OFX", 200)
                        dup = _find_potential_duplicate(entry_type, amount, entry_date, description)
                        candidates.append({
                            "entry_type": entry_type, "amount": amount,
                            "category": "Importado", "description": description,
                            "entry_date": entry_date, "notes": "Importado via OFX",
                            "_dup": dup,
                        })
                    except (ValueError, IndexError) as exc:
                        errors.append({"transaction": i + 1, "error": str(exc)})
            except Exception as exc:
                return jsonify({"error": f"Erro ao processar OFX: {exc}"}), 400
        else:
            return jsonify({"error": "Formato não suportado. Use .csv ou .ofx"}), 400

        # Insert non-duplicates (or all if force=true)
        imported_ids: list[int] = []
        potential_duplicates: list[dict] = []
        for c in candidates:
            dup = c.pop("_dup", None)
            if dup and not force:
                potential_duplicates.append({
                    "candidate": {"entry_type": c["entry_type"], "amount": c["amount"],
                                  "entry_date": c["entry_date"], "description": c["description"]},
                    "matched": dup,
                })
                continue
            imported_ids.append(repo.add_fin_cashflow_entry(c))

        _audit("create", "cashflow_import", None, {
            "filename": filename, "imported": len(imported_ids),
            "duplicates_skipped": len(potential_duplicates), "errors": len(errors),
        })
        return jsonify({
            "ok": True,
            "imported": len(imported_ids),
            "potential_duplicates": potential_duplicates,
            "errors": errors,
        })

    @app.post("/api/finance/cashflow/ocr")
    @limiter.limit("10/minute")
    @require_finance_key
    def finance_cashflow_ocr():
        """OCR de comprovante: imagem → campos pré-preenchidos para lançamento."""
        if "file" not in request.files:
            return jsonify({"ok": False, "error": "Nenhum arquivo enviado (campo 'file')"}), 400

        f = request.files["file"]
        raw_bytes = f.read(5 * 1024 * 1024)  # max 5 MB
        if len(raw_bytes) < 100:
            return jsonify({"ok": False, "error": "Arquivo muito pequeno ou vazio"}), 400

        try:
            import pytesseract  # noqa: PLC0415
            from PIL import Image  # noqa: PLC0415
        except ImportError:
            return jsonify({
                "ok": False,
                "pytesseract_missing": True,
                "error": "Instale pytesseract e Pillow para OCR automático: pip install pytesseract Pillow",
            }), 501

        try:
            import io as _io
            img = Image.open(_io.BytesIO(raw_bytes))
            raw_text: str = pytesseract.image_to_string(img, lang="por")
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Erro ao processar imagem: {exc}"}), 422

        # --- parse date ---
        date_match = re.search(r"\b(\d{2})[/.-](\d{2})[/.-](\d{4})\b", raw_text)
        entry_date = None
        if date_match:
            d, m, y = date_match.group(1), date_match.group(2), date_match.group(3)
            entry_date = f"{y}-{m.zfill(2)}-{d.zfill(2)}"

        # --- parse amount (look for TOTAL / R$ patterns) ---
        amount = None
        total_match = re.search(r"(?:TOTAL|VALOR|PAGO|PAGAR)\D{0,10}([\d.,]+)", raw_text, re.IGNORECASE)
        if not total_match:
            total_match = re.search(r"R\$\s*([\d.,]+)", raw_text, re.IGNORECASE)
        if total_match:
            raw_val = total_match.group(1).replace(".", "").replace(",", ".")
            try:
                amount = round(float(raw_val), 2)
            except ValueError:
                pass

        # --- basic description: first non-empty line, max 100 chars ---
        lines = [l.strip() for l in raw_text.splitlines() if l.strip() and len(l.strip()) > 3]
        description = sanitize_text(lines[0][:100] if lines else "", 100)

        return jsonify({
            "ok": True,
            "date": entry_date,
            "amount": amount,
            "description": description,
            "category": None,
            "raw_text": raw_text[:1000],
        })

    @app.get("/api/finance/cashflow/<int:entry_id>/attachments")
    @limiter.limit("30/minute")
    def finance_cashflow_attachments_list(entry_id: int):
        entry = repo.get_fin_cashflow_entry(entry_id)
        if not entry:
            return jsonify({"error": "Lançamento não encontrado"}), 404
        return jsonify(repo.list_fin_cashflow_attachments(entry_id))

    @app.post("/api/finance/cashflow/<int:entry_id>/attachments")
    @limiter.limit("20/minute")
    @require_finance_key
    def finance_cashflow_attachments_upload(entry_id: int):
        entry = repo.get_fin_cashflow_entry(entry_id)
        if not entry:
            return jsonify({"error": "Lançamento não encontrado"}), 404

        f = request.files.get("file")
        if not f or not f.filename:
            return jsonify({"error": "Envie o arquivo no campo 'file'"}), 400

        raw_name = sanitize_text(str(f.filename), 180).strip() or "anexo.bin"
        safe_name = re.sub(r"[^\w\-. ]", "_", raw_name)
        blob = f.read(2 * 1024 * 1024)
        if not blob:
            return jsonify({"error": "Arquivo vazio"}), 400
        if len(blob) > 2 * 1024 * 1024:
            return jsonify({"error": "Arquivo excede 2 MB"}), 400

        mime_type = sanitize_text(str(f.mimetype or "application/octet-stream"), 120).strip()
        attachment_id = repo.add_fin_cashflow_attachment(
            entry_id=entry_id,
            file_name=safe_name,
            mime_type=mime_type,
            file_blob=blob,
        )
        _audit(
            "add",
            "cashflow_attachment",
            attachment_id,
            {
                "entry_id": entry_id,
                "file_name": safe_name,
                "file_size": len(blob),
                "mime_type": mime_type,
            },
        )
        return jsonify({"ok": True, "id": attachment_id}), 201

    @app.get("/api/finance/cashflow/attachments/<int:attachment_id>/download")
    @limiter.limit("30/minute")
    def finance_cashflow_attachments_download(attachment_id: int):
        row = repo.get_fin_cashflow_attachment(attachment_id)
        if not row:
            return jsonify({"error": "Anexo não encontrado"}), 404

        file_name = sanitize_text(str(row.get("file_name") or "anexo.bin"), 180).strip() or "anexo.bin"
        mime_type = sanitize_text(str(row.get("mime_type") or "application/octet-stream"), 120).strip()
        blob = row.get("file_blob")
        if not isinstance(blob, (bytes, bytearray)):
            return jsonify({"error": "Conteúdo do anexo inválido"}), 500

        return app.response_class(
            bytes(blob),
            mimetype=mime_type,
            headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
        )

    @app.delete("/api/finance/cashflow/attachments/<int:attachment_id>")
    @limiter.limit("20/minute")
    @require_finance_key
    def finance_cashflow_attachments_delete(attachment_id: int):
        row = repo.get_fin_cashflow_attachment(attachment_id)
        if not row:
            return jsonify({"error": "Anexo não encontrado"}), 404
        repo.delete_fin_cashflow_attachment(attachment_id)
        _audit(
            "delete",
            "cashflow_attachment",
            attachment_id,
            {
                "entry_id": int(row.get("entry_id") or 0),
                "file_name": row.get("file_name"),
                "file_size": int(row.get("file_size") or 0),
            },
        )
        return jsonify({"ok": True})

    @app.get("/api/finance/cashflow/closing-pdf")
    @limiter.limit("10/minute")
    def finance_cashflow_closing_pdf():
        month = sanitize_text(str(request.args.get("month", "")), 7).strip()
        if not month:
            month = datetime.now(timezone.utc).strftime("%Y-%m")
        if not re.match(r"^\d{4}-\d{2}$", month):
            return jsonify({"error": "month inválido (use YYYY-MM)"}), 400

        summary = repo.get_fin_cashflow_summary(months=18)
        analytics = repo.get_fin_cashflow_analytics(month=month)
        budget = analytics.get("budget", {})
        totals = analytics.get("totals", {})

        month_rows = [
            row for row in (summary.get("monthly") or []) if str(row.get("month") or "") == month
        ]
        month_row = month_rows[0] if month_rows else {}

        lines = [
            "Fechamento Mensal - Fluxo de Caixa",
            f"Mes de referencia: {month}",
            f"Gerado em: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            "Resumo:",
            f"- Receitas: R$ {float(totals.get('income') or 0):,.2f}",
            f"- Despesas: R$ {float(totals.get('expense') or 0):,.2f}",
            f"- Saldo: R$ {float(totals.get('balance') or 0):,.2f}",
            f"- Taxa de poupanca: {float(totals.get('savings_rate_pct') or 0):.2f}%",
            "",
            "Orcamento:",
            f"- Total gasto: R$ {float(budget.get('total_spent') or 0):,.2f}",
            f"- Total limite: R$ {float(budget.get('total_limit') or 0):,.2f}",
            f"- Restante: R$ {float(budget.get('total_remaining') or 0):,.2f}",
            "",
            "Top categorias de gasto:",
        ]
        for row in (analytics.get("top_expenses") or [])[:5]:
            lines.append(f"- {row.get('category')}: R$ {float(row.get('amount') or 0):,.2f}")

        lines.extend([
            "",
            "Comparativo do mes (serie mensal):",
            f"- Receita mensal: R$ {float(month_row.get('income') or 0):,.2f}",
            f"- Despesa mensal: R$ {float(month_row.get('expense') or 0):,.2f}",
            f"- Saldo mensal: R$ {float(month_row.get('balance') or 0):,.2f}",
        ])

        pdf_bytes = _build_simple_pdf(lines)
        return app.response_class(
            pdf_bytes,
            mimetype="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=fechamento-{month}.pdf",
            },
        )

    @app.post("/api/finance/cashflow/rollover")
    @limiter.limit("10/minute")
    @require_finance_key
    def finance_cashflow_rollover():
        body = request.get_json(silent=True) or {}
        source_month = sanitize_text(str(body.get("source_month", "")), 7).strip()
        target_month = sanitize_text(str(body.get("target_month", "")), 7).strip()
        raw_type = sanitize_text(str(body.get("entry_type", "all")), 12).strip().lower()

        if not re.match(r"^\d{4}-\d{2}$", source_month):
            return jsonify({"error": "source_month inválido (use YYYY-MM)"}), 400
        if not re.match(r"^\d{4}-\d{2}$", target_month):
            return jsonify({"error": "target_month inválido (use YYYY-MM)"}), 400
        if source_month == target_month:
            return jsonify({"error": "source_month e target_month devem ser diferentes"}), 400
        if raw_type not in ("all", "income", "expense"):
            return jsonify({"error": "entry_type inválido (all|income|expense)"}), 400

        entry_type = None if raw_type == "all" else raw_type

        def _target_date(src_date: str, month_key: str) -> str:
            year = int(month_key[:4])
            month = int(month_key[5:7])
            try:
                src_day = int(str(src_date)[8:10])
            except (TypeError, ValueError):
                src_day = 1

            if month == 12:
                next_month_first = datetime(year + 1, 1, 1)
            else:
                next_month_first = datetime(year, month + 1, 1)
            last_day = (next_month_first - timedelta(days=1)).day
            safe_day = max(1, min(last_day, src_day))
            return f"{year:04d}-{month:02d}-{safe_day:02d}"

        source_rows = repo.list_fin_cashflow_entries(
            month=source_month,
            entry_type=entry_type,
            limit=5000,
        )
        target_rows = repo.list_fin_cashflow_entries(
            month=target_month,
            entry_type=entry_type,
            limit=5000,
        )

        existing_signatures: set[tuple[str, float, str, str, str]] = set()
        for row in target_rows:
            entry_date = str(row.get("entry_date") or "")[:10]
            existing_signatures.add(
                (
                    str(row.get("entry_type") or "").strip().lower(),
                    round(float(row.get("amount") or 0), 2),
                    str(row.get("category") or "").strip().lower(),
                    str(row.get("description") or "").strip().lower(),
                    entry_date,
                ),
            )

        created = 0
        skipped = 0
        created_ids: list[int] = []
        for row in source_rows:
            new_date = _target_date(str(row.get("entry_date") or ""), target_month)
            signature = (
                str(row.get("entry_type") or "").strip().lower(),
                round(float(row.get("amount") or 0), 2),
                str(row.get("category") or "").strip().lower(),
                str(row.get("description") or "").strip().lower(),
                new_date,
            )
            if signature in existing_signatures:
                skipped += 1
                continue

            new_id = repo.add_fin_cashflow_entry(
                {
                    "entry_type": signature[0],
                    "amount": signature[1],
                    "category": str(row.get("category") or "").strip(),
                    "description": str(row.get("description") or "").strip(),
                    "entry_date": new_date,
                    "notes": str(row.get("notes") or "").strip(),
                },
            )
            existing_signatures.add(signature)
            created += 1
            created_ids.append(int(new_id))

        _audit(
            "rollover",
            "cashflow",
            None,
            {
                "source_month": source_month,
                "target_month": target_month,
                "entry_type": raw_type,
                "created": created,
                "skipped": skipped,
            },
        )
        return jsonify(
            {
                "ok": True,
                "source_month": source_month,
                "target_month": target_month,
                "entry_type": raw_type,
                "created": created,
                "skipped": skipped,
                "created_ids": created_ids,
            },
        )

    @app.get("/api/finance/cashflow/recurring")
    @limiter.limit("30/minute")
    def finance_cashflow_recurring_list():
        active_only = str(request.args.get("active_only", "1")).strip() not in ("0", "false", "False")
        payload = repo.list_fin_cashflow_recurring(active_only=active_only)
        return jsonify(payload)

    @app.post("/api/finance/cashflow/recurring")
    @limiter.limit("20/minute")
    @require_finance_key
    def finance_cashflow_recurring_add():
        body = request.get_json(silent=True) or {}
        entry_type = sanitize_text(str(body.get("entry_type", "")).strip().lower(), 12)
        if entry_type not in ("income", "expense"):
            return jsonify({"error": "entry_type deve ser income ou expense"}), 400

        _VALID_FREQUENCIES = {"monthly", "quarterly", "yearly"}
        frequency = sanitize_text(str(body.get("frequency", "monthly")).strip().lower(), 20)
        if frequency not in _VALID_FREQUENCIES:
            return jsonify({"error": f"frequency inválida. Use: {', '.join(sorted(_VALID_FREQUENCIES))}"}), 400

        _VALID_DAY_RULES = {"exact", "last_day", "first_weekday", "last_weekday"}
        day_rule = sanitize_text(str(body.get("day_rule", "exact")).strip().lower(), 20)
        if day_rule not in _VALID_DAY_RULES:
            return jsonify({"error": f"day_rule inválido. Use: {', '.join(sorted(_VALID_DAY_RULES))}"}), 400

        try:
            amount = float(body.get("amount", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "amount inválido"}), 400
        if not _is_finite_number(amount) or amount <= 0:
            return jsonify({"error": "amount deve ser > 0"}), 400

        day_of_month = int(body.get("day_of_month", 1))
        day_of_month = max(1, min(31, day_of_month))

        start_date = sanitize_text(str(body.get("start_date", "")), 10).strip() or None
        end_date = sanitize_text(str(body.get("end_date", "")), 10).strip() or None
        if start_date and not re.match(r"^\d{4}-\d{2}-\d{2}$", start_date):
            return jsonify({"error": "start_date inválida (use YYYY-MM-DD)"}), 400
        if end_date and not re.match(r"^\d{4}-\d{2}-\d{2}$", end_date):
            return jsonify({"error": "end_date inválida (use YYYY-MM-DD)"}), 400

        payload = {
            "active": bool(body.get("active", True)),
            "entry_type": entry_type,
            "amount": amount,
            "category": sanitize_text(str(body.get("category", "")), 60),
            "subcategory": sanitize_text(str(body.get("subcategory", "")), 60),
            "cost_center": sanitize_text(str(body.get("cost_center", "")), 60),
            "description": sanitize_text(str(body.get("description", "")), 160),
            "notes": sanitize_text(str(body.get("notes", "")), 500),
            "tags": _normalize_tags(body.get("tags")),
            "frequency": frequency,
            "day_of_month": day_of_month,
            "day_rule": day_rule,
            "start_date": start_date,
            "end_date": end_date,
        }
        recurring_id = repo.add_fin_cashflow_recurring(payload)
        _audit("add", "cashflow_recurring", recurring_id, {"after": {**payload, "id": recurring_id}})
        return jsonify({"ok": True, "id": recurring_id}), 201

    @app.put("/api/finance/cashflow/recurring/<int:recurring_id>")
    @limiter.limit("20/minute")
    @require_finance_key
    def finance_cashflow_recurring_update(recurring_id: int):
        body = request.get_json(silent=True) or {}
        data: dict[str, object] = {}

        if "active" in body:
            data["active"] = bool(body.get("active"))
        if "entry_type" in body:
            entry_type = sanitize_text(str(body.get("entry_type", "")).strip().lower(), 12)
            if entry_type not in ("income", "expense"):
                return jsonify({"error": "entry_type deve ser income ou expense"}), 400
            data["entry_type"] = entry_type
        if "amount" in body:
            try:
                amount = float(body.get("amount", 0))
            except (TypeError, ValueError):
                return jsonify({"error": "amount inválido"}), 400
            if not _is_finite_number(amount) or amount <= 0:
                return jsonify({"error": "amount deve ser > 0"}), 400
            data["amount"] = amount
        if "category" in body:
            data["category"] = sanitize_text(str(body.get("category", "")), 60)
        if "subcategory" in body:
            data["subcategory"] = sanitize_text(str(body.get("subcategory", "")), 60)
        if "cost_center" in body:
            data["cost_center"] = sanitize_text(str(body.get("cost_center", "")), 60)
        if "description" in body:
            data["description"] = sanitize_text(str(body.get("description", "")), 160)
        if "notes" in body:
            data["notes"] = sanitize_text(str(body.get("notes", "")), 500)
        if "tags" in body:
            data["tags"] = _normalize_tags(body.get("tags"))
        if "frequency" in body:
            frequency = sanitize_text(str(body.get("frequency", "monthly")).strip().lower(), 20)
            if frequency not in {"monthly", "quarterly", "yearly"}:
                return jsonify({"error": "frequency inválida (monthly|quarterly|yearly)"}), 400
            data["frequency"] = frequency
        if "day_rule" in body:
            day_rule = sanitize_text(str(body.get("day_rule", "exact")).strip().lower(), 20)
            if day_rule not in {"exact", "last_day", "first_weekday", "last_weekday"}:
                return jsonify({"error": "day_rule inválido"}), 400
            data["day_rule"] = day_rule
        if "day_of_month" in body:
            dom = int(body.get("day_of_month", 1))
            data["day_of_month"] = max(1, min(31, dom))
        if "start_date" in body:
            start_date = sanitize_text(str(body.get("start_date", "")), 10).strip() or None
            if start_date and not re.match(r"^\d{4}-\d{2}-\d{2}$", start_date):
                return jsonify({"error": "start_date inválida (use YYYY-MM-DD)"}), 400
            data["start_date"] = start_date
        if "end_date" in body:
            end_date = sanitize_text(str(body.get("end_date", "")), 10).strip() or None
            if end_date and not re.match(r"^\d{4}-\d{2}-\d{2}$", end_date):
                return jsonify({"error": "end_date inválida (use YYYY-MM-DD)"}), 400
            data["end_date"] = end_date

        if not data:
            return jsonify({"error": "Nenhum campo válido para atualizar"}), 400
        if not repo.update_fin_cashflow_recurring(recurring_id, data):
            return jsonify({"error": "Recorrência não encontrada"}), 404
        _audit("update", "cashflow_recurring", recurring_id, {"fields": sorted(list(data.keys()))})
        return jsonify({"ok": True})

    @app.delete("/api/finance/cashflow/recurring/<int:recurring_id>")
    @limiter.limit("20/minute")
    @require_finance_key
    def finance_cashflow_recurring_delete(recurring_id: int):
        if not repo.delete_fin_cashflow_recurring(recurring_id):
            return jsonify({"error": "Recorrência não encontrada"}), 404
        _audit("delete", "cashflow_recurring", recurring_id, None)
        return jsonify({"ok": True})

    @app.post("/api/finance/cashflow/recurring/run")
    @limiter.limit("20/minute")
    @require_finance_key
    def finance_cashflow_recurring_run():
        body = request.get_json(silent=True) or {}
        month = sanitize_text(str(body.get("month", "")), 7).strip()
        if not month:
            month = datetime.now(timezone.utc).strftime("%Y-%m")
        if not re.match(r"^\d{4}-\d{2}$", month):
            return jsonify({"error": "month inválido (use YYYY-MM)"}), 400

        result = repo.run_fin_cashflow_recurring_for_month(month)
        _audit("run", "cashflow_recurring", None, result)
        return jsonify({"ok": True, **result})

    @app.post("/api/finance/cashflow")
    @limiter.limit("20/minute")
    @require_finance_key
    def finance_add_cashflow():
        body = request.get_json(silent=True) or {}
        entry_type = sanitize_text(str(body.get("entry_type", "")).lower(), 12)
        if entry_type not in ("income", "expense"):
            return jsonify({"error": "entry_type deve ser income ou expense"}), 400

        try:
            amount = float(body.get("amount", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "amount inválido"}), 400
        if not _is_finite_number(amount) or amount <= 0:
            return jsonify({"error": "amount deve ser > 0"}), 400

        entry_date = sanitize_text(
            str(body.get("entry_date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")),
            10,
        )
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", entry_date):
            return jsonify({"error": "entry_date inválida (use YYYY-MM-DD)"}), 400

        payment_status = sanitize_text(str(body.get("payment_status", "")), 12).strip().lower()
        if payment_status and payment_status not in ("pending", "paid"):
            return jsonify({"error": "payment_status inválido (pending|paid)"}), 400
        settled_at: str | None = None
        if payment_status == "paid":
            settled_at = sanitize_text(
                str(body.get("settled_at") or entry_date),
                10,
            )
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", settled_at):
                return jsonify({"error": "settled_at inválida (use YYYY-MM-DD)"}), 400

        data = {
            "entry_type": entry_type,
            "amount": amount,
            "category": sanitize_text(str(body.get("category", "")), 60),
            "subcategory": sanitize_text(str(body.get("subcategory", "")), 60),
            "cost_center": sanitize_text(str(body.get("cost_center", "")), 60),
            "description": sanitize_text(str(body.get("description", "")), 160),
            "entry_date": entry_date,
            "notes": sanitize_text(str(body.get("notes", "")), 500),
            "tags": _normalize_tags(body.get("tags")),
        }
        entry_id = repo.add_fin_cashflow_entry(data)
        if payment_status:
            repo.set_fin_cashflow_status(entry_id, payment_status, settled_at)

        _audit(
            "add",
            "cashflow",
            entry_id,
            {
                "entry_type": entry_type,
                "amount": amount,
                "payment_status": payment_status or ("paid" if entry_type == "income" else "pending"),
                "settled_at": settled_at,
                "after": {
                    **data,
                    "id": entry_id,
                    "payment_status": payment_status or ("paid" if entry_type == "income" else "pending"),
                    "settled_at": settled_at,
                },
            },
        )
        return jsonify({"ok": True, "id": entry_id}), 201

    @app.put("/api/finance/cashflow/<int:entry_id>")
    @limiter.limit("20/minute")
    @require_finance_key
    def finance_update_cashflow(entry_id: int):
        body = request.get_json(silent=True) or {}
        if not body:
            return jsonify({"error": "JSON inválido"}), 400

        before = repo.get_fin_cashflow_entry(entry_id)
        if not before:
            return jsonify({"error": "Lançamento não encontrado"}), 404
        before_status = repo.get_fin_cashflow_status(entry_id)

        data: dict[str, object] = {}
        if "entry_type" in body:
            entry_type = sanitize_text(str(body.get("entry_type", "")).lower(), 12)
            if entry_type not in ("income", "expense"):
                return jsonify({"error": "entry_type deve ser income ou expense"}), 400
            data["entry_type"] = entry_type
        if "amount" in body:
            try:
                amount = float(body.get("amount", 0))
            except (TypeError, ValueError):
                return jsonify({"error": "amount inválido"}), 400
            if not _is_finite_number(amount) or amount <= 0:
                return jsonify({"error": "amount deve ser > 0"}), 400
            data["amount"] = amount
        if "entry_date" in body:
            entry_date = sanitize_text(str(body.get("entry_date") or ""), 10)
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", entry_date):
                return jsonify({"error": "entry_date inválida (use YYYY-MM-DD)"}), 400
            data["entry_date"] = entry_date
        if "category" in body:
            data["category"] = sanitize_text(str(body.get("category", "")), 60)
        if "subcategory" in body:
            data["subcategory"] = sanitize_text(str(body.get("subcategory", "")), 60)
        if "cost_center" in body:
            data["cost_center"] = sanitize_text(str(body.get("cost_center", "")), 60)
        if "description" in body:
            data["description"] = sanitize_text(str(body.get("description", "")), 160)
        if "notes" in body:
            data["notes"] = sanitize_text(str(body.get("notes", "")), 500)
        if "tags" in body:
            data["tags"] = _normalize_tags(body.get("tags"))

        payment_status = None
        settled_at = None
        if "payment_status" in body:
            payment_status = sanitize_text(
                str(body.get("payment_status", "")),
                12,
            ).strip().lower()
            if payment_status not in ("pending", "paid"):
                return jsonify({"error": "payment_status inválido (pending|paid)"}), 400

            if payment_status == "paid":
                settled_at = sanitize_text(
                    str(
                        body.get("settled_at")
                        or body.get("entry_date")
                        or before.get("entry_date")
                        or datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    ),
                    10,
                )
                if not re.match(r"^\d{4}-\d{2}-\d{2}$", settled_at):
                    return jsonify({"error": "settled_at inválida (use YYYY-MM-DD)"}), 400

        if not data and payment_status is None:
            return jsonify({"error": "Nenhum campo válido para atualizar"}), 400

        if data and not repo.update_fin_cashflow_entry(entry_id, data):
            return jsonify({"error": "Lançamento não encontrado"}), 404

        if payment_status is not None:
            repo.set_fin_cashflow_status(entry_id, payment_status, settled_at)

        after = repo.get_fin_cashflow_entry(entry_id) or {}
        after_status = repo.get_fin_cashflow_status(entry_id)
        _audit(
            "update",
            "cashflow",
            entry_id,
            {
                "fields": sorted(list(data.keys())),
                "before": {**before, "payment_status": before_status.get("status"), "settled_at": before_status.get("settled_at")},
                "after": {**after, "payment_status": after_status.get("status"), "settled_at": after_status.get("settled_at")},
            },
        )
        return jsonify({"ok": True})

    @app.put("/api/finance/cashflow/<int:entry_id>/status")
    @limiter.limit("20/minute")
    @require_finance_key
    def finance_update_cashflow_status(entry_id: int):
        body = request.get_json(silent=True) or {}
        raw_status = sanitize_text(str(body.get("status", "")), 12).strip().lower()
        if raw_status not in ("pending", "paid"):
            return jsonify({"error": "status inválido (pending|paid)"}), 400

        entry = repo.get_fin_cashflow_entry(entry_id)
        if not entry:
            return jsonify({"error": "Lançamento não encontrado"}), 404

        settled_at = None
        if raw_status == "paid":
            settled_at = sanitize_text(
                str(
                    body.get("settled_at")
                    or entry.get("entry_date")
                    or datetime.now(timezone.utc).strftime("%Y-%m-%d")
                ),
                10,
            )
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", settled_at):
                return jsonify({"error": "settled_at inválida (use YYYY-MM-DD)"}), 400

        before_status = repo.get_fin_cashflow_status(entry_id)
        repo.set_fin_cashflow_status(entry_id, raw_status, settled_at)
        after_status = repo.get_fin_cashflow_status(entry_id)
        _audit(
            "status_update",
            "cashflow",
            entry_id,
            {
                "before_status": before_status,
                "after_status": after_status,
            },
        )
        return jsonify({
            "ok": True,
            "id": entry_id,
            "status": after_status.get("status"),
            "settled_at": after_status.get("settled_at"),
        })

    @app.delete("/api/finance/cashflow/<int:entry_id>")
    @limiter.limit("20/minute")
    @require_finance_key
    def finance_delete_cashflow(entry_id: int):
        before = repo.get_fin_cashflow_entry(entry_id)
        before_status = repo.get_fin_cashflow_status(entry_id)
        repo.delete_fin_cashflow_entry(entry_id)
        _audit(
            "delete",
            "cashflow",
            entry_id,
            {
                "before": {
                    **(before or {}),
                    "payment_status": before_status.get("status"),
                    "settled_at": before_status.get("settled_at"),
                },
            },
        )
        return jsonify({"ok": True})

    @app.get("/api/finance/goals/passive-income")
    @limiter.limit("30/minute")
    def finance_get_passive_income_goal():
        cache_key = "finance:passive-income-goal"
        cached = cache.get(cache_key)
        if cached:
            return jsonify(cached)

        raw_target = repo.get_setting(
            "finance_passive_income_goal_monthly",
            "0",
        )
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
        cache.set(
            cache_key,
            payload,
            FINANCE_CACHE_TTLS["passive_income_goal"],
        )
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
        repo.set_setting(
            "finance_passive_income_goal_monthly",
            f"{target_monthly:.2f}",
        )
        repo.set_setting("finance_passive_income_goal_note", note)
        _invalidate_cache_prefixes("finance:passive-income-goal")
        _audit(
            "update",
            "passive_income_goal",
            None,
            {"target_monthly": target_monthly},
        )
        return jsonify(
            {
                "ok": True,
                "target_monthly": target_monthly,
                "note": note,
            },
        )

    # ── Excel / CSV Import ──────────────────────────────────

    # Column name aliases (Portuguese / English / broker formats)
    _COL_MAP: dict[str, str] = {}
    for _alias, _field in {
        "simbolo": "symbol", "símbolo": "symbol", "symbol": "symbol",
        "ticker": "symbol", "ativo": "symbol", "codigo": "symbol",
        "código": "symbol", "papel": "symbol",
        "nome": "name", "name": "name",
        "tipo": "asset_type", "type": "asset_type", "asset_type": "asset_type",
        "tipo_ativo": "asset_type", "classe": "asset_type",
        "operacao": "tx_type", "operação": "tx_type", "tx_type": "tx_type",
        "tipo_operacao": "tx_type", "tipo_operação": "tx_type",
        "cv": "tx_type", "c/v": "tx_type",
        "quantidade": "quantity", "qtd": "quantity", "qtde": "quantity",
        "qty": "quantity", "quantity": "quantity",
        "preco": "price", "preço": "price", "price": "price",
        "valor_unitario": "price", "preco_unitario": "price",
        "preço_unitário": "price",
        "taxas": "fees", "taxa": "fees", "fees": "fees",
        "corretagem": "fees", "emolumentos": "fees",
        "data": "date", "date": "date", "data_operacao": "date",
        "data_operação": "date",
        "notas": "notes", "notes": "notes", "observacao": "notes",
        "observação": "notes", "obs": "notes",
        "moeda": "currency", "currency": "currency",
    }.items():
        _COL_MAP[_alias] = _field

    def _normalize_col(name: str) -> str:
        """Normalize a column header to a known field name."""
        clean = (
            name.strip()
            .lower()
            .replace(" ", "_")
            .replace("-", "_")
        )
        # Remove accents with simple mapping
        for a, b in [("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"),
                      ("ú", "u"), ("ã", "a"), ("õ", "o"), ("ç", "c")]:
            clean = clean.replace(a, b)
        return _COL_MAP.get(clean, clean)

    def _parse_tx_type(val: str) -> str:
        v = val.strip().lower()
        if v in ("c", "compra", "buy", "b"):
            return "buy"
        if v in ("v", "venda", "sell", "s"):
            return "sell"
        return "buy"

    def _parse_asset_type(val: str) -> str:
        v = val.strip().lower()
        type_map = {
            "acao": "stock", "ação": "stock", "stock": "stock",
            "acoes": "stock", "ações": "stock",
            "fii": "fii", "crypto": "crypto", "cripto": "crypto",
            "criptomoeda": "crypto", "bitcoin": "crypto",
            "etf": "etf", "fundo": "fund", "fund": "fund",
            "renda fixa": "renda-fixa", "renda-fixa": "renda-fixa",
            "rf": "renda-fixa", "tesouro": "renda-fixa",
        }
        return type_map.get(v, "stock")

    def _parse_number(val: str) -> float:
        """Parse number from various formats (1.234,56 or 1,234.56)."""
        v = str(val).strip().replace("R$", "").replace("$", "").strip()
        if not v or v == "-":
            return 0.0
        # Brazilian format: 1.234,56
        if "," in v and "." in v:
            if v.rindex(",") > v.rindex("."):
                v = v.replace(".", "").replace(",", ".")
            else:
                v = v.replace(",", "")
        elif "," in v:
            v = v.replace(",", ".")
        return float(v)

    @app.post("/api/finance/import")
    @limiter.limit("5/minute")
    @require_finance_key
    def finance_import():
        """Import assets & transactions from CSV or Excel file."""
        f = request.files.get("file")
        if not f or not f.filename:
            return jsonify({"error": "Envie um arquivo CSV ou Excel"}), 400

        fname = f.filename.lower()
        rows: list[dict] = []

        try:
            if fname.endswith(".csv") or fname.endswith(".tsv"):
                # CSV / TSV
                raw = f.read()
                # Try UTF-8 first, then latin-1
                try:
                    text = raw.decode("utf-8-sig")
                except UnicodeDecodeError:
                    text = raw.decode("latin-1")
                sep = "\t" if fname.endswith(".tsv") else None
                if sep is None:
                    # Auto-detect separator
                    first_line = text.split("\n")[0]
                    if "\t" in first_line:
                        sep = "\t"
                    elif ";" in first_line:
                        sep = ";"
                    else:
                        sep = ","
                reader = csv.DictReader(
                    io.StringIO(text), delimiter=sep,
                )
                for row in reader:
                    mapped = {}
                    for k, v in row.items():
                        if k and v:
                            mapped[_normalize_col(k)] = v.strip()
                    if mapped.get("symbol"):
                        rows.append(mapped)

            elif fname.endswith((".xlsx", ".xls")):
                import openpyxl

                wb = openpyxl.load_workbook(
                    io.BytesIO(f.read()), read_only=True,
                )
                ws = wb.active
                headers: list[str] = []
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    if i == 0:
                        headers = [
                            _normalize_col(str(c or "")) for c in row
                        ]
                        continue
                    mapped = {}
                    for j, val in enumerate(row):
                        if j < len(headers) and val is not None:
                            mapped[headers[j]] = str(val).strip()
                    if mapped.get("symbol"):
                        rows.append(mapped)
                wb.close()
            else:
                return jsonify({
                    "error": "Formato não suportado. Use .csv, .tsv ou .xlsx",
                }), 400
        except Exception as exc:
            logger.warning("Import parse error: %s", exc)
            return jsonify({"error": f"Erro ao ler arquivo: {exc}"}), 400

        if not rows:
            return jsonify({
                "error": "Nenhuma linha válida encontrada. "
                "O arquivo precisa ter ao menos uma coluna 'símbolo' ou 'symbol'.",
            }), 400

        imported = 0
        errors_list: list[str] = []
        has_tx_cols = any(
            r.get("quantity") or r.get("price") for r in rows
        )

        for idx, row in enumerate(rows, start=2):
            try:
                symbol = sanitize_text(
                    row["symbol"].upper().strip(), 20,
                )
                name = sanitize_text(
                    row.get("name", symbol), 100,
                )
                asset_type = _parse_asset_type(
                    row.get("asset_type", "stock"),
                )
                currency = sanitize_text(
                    row.get("currency", "BRL").upper(), 10,
                )

                # Upsert the asset
                asset_id = repo.upsert_fin_asset({
                    "symbol": symbol,
                    "name": name,
                    "asset_type": asset_type,
                    "currency": currency,
                })

                # If has transaction columns, also create transaction
                if has_tx_cols and row.get("quantity") and row.get("price"):
                    qty = _parse_number(row["quantity"])
                    price = _parse_number(row["price"])
                    fees = _parse_number(row.get("fees", "0"))
                    tx_type = _parse_tx_type(row.get("tx_type", "buy"))
                    tx_date = row.get("date", "")
                    if not tx_date:
                        tx_date = datetime.now().strftime("%Y-%m-%d")

                    repo.add_fin_transaction({
                        "asset_id": asset_id,
                        "tx_type": tx_type,
                        "quantity": qty,
                        "price": price,
                        "total": qty * price + fees,
                        "fees": fees,
                        "notes": sanitize_text(
                            row.get("notes", "Importado"), 500,
                        ),
                        "tx_date": tx_date,
                    })
                    _recalc_portfolio(repo, asset_id)

                imported += 1
            except Exception as exc:
                errors_list.append(f"Linha {idx}: {exc}")

        _invalidate_financial_state_cache(include_market=True)
        return jsonify({
            "ok": True,
            "imported": imported,
            "total_rows": len(rows),
            "errors": errors_list[:20],
        }), 200 if imported else 400

    # ── Import Template (sample CSV) ───────────────────────

    @app.get("/api/finance/import-template")
    def finance_import_template():
        header = "simbolo;nome;tipo;operacao;quantidade;preco;taxas;data;notas\n"
        sample = "PETR4;Petrobras PN;acao;compra;100;35.50;4.90;2026-01-15;Minha primeira compra\n"
        content = header + sample
        return (
            content,
            200,
            {
                "Content-Type": "text/csv; charset=utf-8",
                "Content-Disposition": "attachment; filename=modelo_importacao.csv",
            },
        )

    # ── Import Nota de Corretagem (brokerage note) ─────────

    @app.post("/api/finance/import-nota")
    @limiter.limit("5/minute")
    @require_finance_key
    def finance_import_nota():
        """Import brokerage note (nota de corretagem) CSV/Excel.

        Supports B3/CEI export and common broker formats.
        Expected columns (flexible mapping):
          - papel/titulo/ativo/symbol
          - tipo negociacao/operacao (C/V or Compra/Venda)
          - quantidade/qtd
          - preco/valor unitario
          - valor total/total
          - taxa corretagem/corretagem/emolumentos
          - data pregao/data/date
        """
        f = request.files.get("file")
        if not f or not f.filename:
            return jsonify({
                "error": "Envie o arquivo da nota de corretagem",
            }), 400

        fname = f.filename.lower()

        # Extra column mappings for brokerage notes
        nota_col_map = {
            "papel": "symbol", "titulo": "symbol", "ativo": "symbol",
            "cod_negociacao": "symbol", "codigo": "symbol",
            "especificacao_titulo": "name",
            "tipo_negociacao": "tx_type", "tipo_operacao": "tx_type",
            "c_v": "tx_type", "cv": "tx_type", "operacao": "tx_type",
            "quantidade": "quantity", "qtd": "quantity",
            "qtde": "quantity", "qtd_negociada": "quantity",
            "preco": "price", "preco_unitario": "price",
            "valor_unitario": "price", "pu": "price",
            "preco_ajuste": "price",
            "valor_total": "total", "valor_operacao": "total",
            "valor_liquido": "total",
            "corretagem": "fees", "taxa_corretagem": "fees",
            "emolumentos": "fees2", "taxa_liquidacao": "fees3",
            "impostos": "fees4",
            "data_pregao": "date", "data_negocio": "date",
            "data": "date", "dt_negocio": "date",
            "prazo": "notes",
            "mercado": "market",
        }

        def normalize_nota_col(col: str) -> str:
            """Normalise brokerage note column name."""
            c = col.strip().lower()
            for a, b in [("á", "a"), ("é", "e"), ("í", "i"),
                         ("ó", "o"), ("ú", "u"), ("ã", "a"),
                         ("õ", "o"), ("ç", "c")]:
                c = c.replace(a, b)
            c = c.replace(" ", "_").replace("-", "_").replace("/", "_")
            return nota_col_map.get(c, _normalize_col(c))

        rows: list[dict] = []
        try:
            if fname.endswith((".csv", ".tsv")):
                raw = f.read()
                try:
                    text = raw.decode("utf-8-sig")
                except UnicodeDecodeError:
                    text = raw.decode("latin-1")
                first_line = text.split("\n")[0]
                sep = "\t" if "\t" in first_line else (
                    ";" if ";" in first_line else ","
                )
                reader = csv.DictReader(
                    io.StringIO(text), delimiter=sep,
                )
                for row in reader:
                    mapped = {}
                    for k, v in row.items():
                        if k and v:
                            mapped[normalize_nota_col(k)] = v.strip()
                    if mapped.get("symbol"):
                        rows.append(mapped)
            elif fname.endswith((".xlsx", ".xls")):
                import openpyxl

                wb = openpyxl.load_workbook(
                    io.BytesIO(f.read()), read_only=True,
                )
                ws = wb.active
                headers: list[str] = []
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    if i == 0:
                        headers = [
                            normalize_nota_col(str(c or ""))
                            for c in row
                        ]
                        continue
                    mapped = {}
                    for j, val in enumerate(row):
                        if j < len(headers) and val is not None:
                            mapped[headers[j]] = str(val).strip()
                    if mapped.get("symbol"):
                        rows.append(mapped)
                wb.close()
            else:
                return jsonify({
                    "error": "Use arquivo .csv, .tsv ou .xlsx",
                }), 400
        except Exception as exc:
            logger.warning("Nota import parse: %s", exc)
            return jsonify({"error": f"Erro ao ler: {exc}"}), 400

        if not rows:
            return jsonify({
                "error": "Nenhuma operação encontrada. "
                "Verifique se o arquivo contém colunas como "
                "'papel', 'quantidade', 'preço'.",
            }), 400

        imported = 0
        errors_list: list[str] = []

        for idx, row in enumerate(rows, 2):
            try:
                symbol = sanitize_text(
                    row["symbol"].upper().strip(), 20,
                )
                # Guess asset type from symbol
                at = "stock"
                if symbol.endswith("11") and len(symbol) >= 5:
                    at = "fii"
                elif symbol.endswith("11B"):
                    at = "fii"

                name = sanitize_text(
                    row.get("name", symbol), 100,
                )
                asset_id = repo.upsert_fin_asset({
                    "symbol": symbol,
                    "name": name,
                    "asset_type": at,
                    "currency": "BRL",
                })

                qty = _parse_number(row.get("quantity", "0"))
                price = _parse_number(row.get("price", "0"))
                if qty <= 0 or price <= 0:
                    errors_list.append(
                        f"Linha {idx}: quantidade ou preço inválido",
                    )
                    continue

                # Aggregate fees from multiple fee columns
                fees = sum(
                    _parse_number(row.get(k, "0"))
                    for k in ("fees", "fees2", "fees3", "fees4")
                )

                total = _parse_number(row.get("total", "0"))
                if total <= 0:
                    total = qty * price + fees

                tx_type = _parse_tx_type(row.get("tx_type", "buy"))
                tx_date = row.get("date", "")
                if not tx_date:
                    tx_date = datetime.now().strftime("%Y-%m-%d")

                repo.add_fin_transaction({
                    "asset_id": asset_id,
                    "tx_type": tx_type,
                    "quantity": qty,
                    "price": price,
                    "total": total,
                    "fees": fees,
                    "notes": sanitize_text(
                        row.get("notes", "Importado de nota"),
                        500,
                    ),
                    "tx_date": tx_date,
                })
                _recalc_portfolio(repo, asset_id)
                imported += 1
            except Exception as exc:
                errors_list.append(f"Linha {idx}: {exc}")

        _invalidate_financial_state_cache(include_market=True)
        return jsonify({
            "ok": True,
            "imported": imported,
            "total_rows": len(rows),
            "errors": errors_list[:20],
        }), 200 if imported else 400

    # ── Import B3 Movimentação (CEI) ──────────────────────

    @app.post("/api/finance/import-b3")
    @limiter.limit("5/minute")
    @require_finance_key
    def finance_import_b3():
        """Import B3/CEI 'Movimentação' xlsx export.

        Expected columns:
          Entrada/Saída | Data | Movimentação | Produto |
          Instituição | Quantidade | Preço unitário | Valor da Operação
        """
        f = request.files.get("file")
        if not f or not f.filename:
            return jsonify({"error": "Envie o arquivo xlsx"}), 400

        fname = f.filename.lower()
        if not fname.endswith((".xlsx", ".xls")):
            return jsonify({
                "error": "Formato não suportado. Use .xlsx",
            }), 400

        # Movement types that generate BUY/SELL transactions
        TX_BUY_TYPES = {
            "transferência - liquidação",
            "bonificação em ativos",
            "fração em ativos",
        }
        TX_TRADE = "compra / venda"
        TX_SELL_TYPES = {"leilão de fração"}
        # Movement types that generate dividends
        DIV_TYPE_MAP = {
            "rendimento": "rendimento",
            "dividendo": "dividendo",
            "juros sobre capital próprio": "jcp",
            "juros sobre capital próprio - transferido": "jcp",
        }
        # Movement types to skip
        SKIP_TYPES = {
            "atualização",
            "transferência",
            "cessão de direitos",
            "cessão de direitos - solicitada",
            "direito de subscrição",
            "direitos de subscrição - não exercido",
        }

        try:
            import openpyxl

            wb = openpyxl.load_workbook(
                io.BytesIO(f.read()), read_only=False,
            )
            # Find the Movimentação sheet or use active
            ws = None
            for name in wb.sheetnames:
                if "movimenta" in name.lower():
                    ws = wb[name]
                    break
            if ws is None:
                ws = wb.active

            raw_rows: list[dict] = []
            headers: list[str] = []
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i == 0:
                    headers = [
                        str(c or "").strip() for c in row
                    ]
                    continue
                d: dict = {}
                for j, val in enumerate(row):
                    if j < len(headers):
                        d[headers[j]] = val
                raw_rows.append(d)
            wb.close()
        except Exception as exc:
            logger.warning("B3 import parse error: %s", exc)
            return jsonify({"error": f"Erro ao ler: {exc}"}), 400

        if not raw_rows:
            return jsonify({
                "error": "Arquivo vazio ou sem dados.",
            }), 400

        # Validate expected columns
        expected = {"Produto", "Movimentação", "Quantidade"}
        found = set(headers)
        if not expected.issubset(found):
            missing = expected - found
            return jsonify({
                "error": (
                    "Colunas esperadas não encontradas: "
                    f"{', '.join(missing)}. "
                    "Este arquivo é um export de Movimentação "
                    "do B3/CEI?"
                ),
            }), 400

        tx_imported = 0
        div_imported = 0
        skipped = 0
        errors_list: list[str] = []

        for idx, row in enumerate(raw_rows, start=2):
            try:
                mov = str(row.get("Movimentação", "")).strip()
                mov_lower = mov.lower()
                entrada = str(
                    row.get("Entrada/Saída", ""),
                ).strip().lower()
                produto = str(row.get("Produto", "")).strip()
                qty_raw = row.get("Quantidade")
                price_raw = row.get("Preço unitário")
                val_raw = row.get("Valor da Operação")

                # Skip known non-actionable types
                if mov_lower in SKIP_TYPES:
                    skipped += 1
                    continue

                # Extract ticker and name from Produto
                if " - " in produto:
                    parts = produto.split(" - ", 1)
                    symbol = parts[0].strip().upper()
                    name = parts[1].strip()
                else:
                    symbol = produto.strip().upper()
                    name = symbol

                if not symbol:
                    skipped += 1
                    continue

                # Skip subscription rights tickers (e.g. XPML12)
                # that are not actual tradeable assets
                if symbol.endswith("12") and mov_lower in (
                    "cessão de direitos",
                    "direito de subscrição",
                ):
                    skipped += 1
                    continue

                # Parse date DD/MM/YYYY → YYYY-MM-DD
                raw_date = str(row.get("Data", "")).strip()
                tx_date = ""
                if "/" in raw_date:
                    dp = raw_date.split("/")
                    if len(dp) == 3:
                        tx_date = (
                            f"{dp[2]}-{dp[1].zfill(2)}"
                            f"-{dp[0].zfill(2)}"
                        )
                if not tx_date:
                    tx_date = datetime.now().strftime("%Y-%m-%d")

                # Parse qty, price, total
                qty = _parse_number(str(qty_raw or "0"))
                price = _parse_number(str(price_raw or "0"))
                total = _parse_number(str(val_raw or "0"))

                # Auto-detect asset type
                asset_type = "stock"
                sym_upper = symbol.upper()
                if sym_upper.endswith(("11", "11B")):
                    if len(sym_upper) >= 5:
                        asset_type = "fii"
                elif sym_upper.startswith("CDB"):
                    asset_type = "renda-fixa"

                # Truncate name to 100 chars
                name = sanitize_text(name, 100)
                symbol = sanitize_text(symbol, 20)

                # ── Handle DIVIDENDS ──
                if mov_lower in DIV_TYPE_MAP:
                    if qty <= 0 or price <= 0:
                        skipped += 1
                        continue

                    div_type = DIV_TYPE_MAP[mov_lower]
                    asset_id = repo.upsert_fin_asset({
                        "symbol": symbol,
                        "name": name,
                        "asset_type": asset_type,
                        "currency": "BRL",
                    })
                    repo.add_fin_dividend({
                        "asset_id": asset_id,
                        "div_type": div_type,
                        "amount_per_share": price,
                        "total_amount": total if total > 0
                        else qty * price,
                        "quantity": qty,
                        "ex_date": tx_date,
                        "pay_date": tx_date,
                        "notes": f"Importado B3: {mov}",
                    })
                    div_imported += 1
                    continue

                # ── Handle TRANSACTIONS ──
                tx_type = None

                if mov_lower == TX_TRADE:
                    # COMPRA / VENDA: Debito=buy, Credito=sell
                    tx_type = (
                        "buy" if entrada == "debito"
                        else "sell"
                    )
                elif mov_lower in TX_BUY_TYPES:
                    tx_type = "buy"
                elif mov_lower in TX_SELL_TYPES:
                    tx_type = "sell"
                else:
                    # Unknown type, skip
                    skipped += 1
                    continue

                if qty <= 0 or price <= 0:
                    # Bonificação / fração may have price=0
                    if mov_lower in (
                        "bonificação em ativos",
                        "fração em ativos",
                    ) and qty > 0:
                        price = 0.0
                        total = 0.0
                    else:
                        skipped += 1
                        continue

                if total <= 0:
                    total = qty * price

                asset_id = repo.upsert_fin_asset({
                    "symbol": symbol,
                    "name": name,
                    "asset_type": asset_type,
                    "currency": "BRL",
                })
                repo.add_fin_transaction({
                    "asset_id": asset_id,
                    "tx_type": tx_type,
                    "quantity": qty,
                    "price": price,
                    "total": total,
                    "fees": 0,
                    "notes": f"Importado B3: {mov}",
                    "tx_date": tx_date,
                })
                _recalc_portfolio(repo, asset_id)
                tx_imported += 1

            except Exception as exc:
                errors_list.append(f"Linha {idx}: {exc}")

        _invalidate_financial_state_cache(
            include_market=True,
            include_dividends=True,
        )
        total_imported = tx_imported + div_imported
        return jsonify({
            "ok": total_imported > 0,
            "transactions": tx_imported,
            "dividends": div_imported,
            "skipped": skipped,
            "total_rows": len(raw_rows),
            "errors": errors_list[:20],
        }), 200 if total_imported else 400

    # ── Dividends CRUD ─────────────────────────────────────

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
        # Auto-calc total if only per_share given
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

    # ── Asset Price History ─────────────────────────────────

    @app.get("/api/finance/asset-history/<int:asset_id>")
    @limiter.limit("30/minute")
    def finance_asset_history_alt(asset_id: int):
        limit = min(3650, max(1, int(request.args.get("limit", "90"))))
        tx_sig = repo.get_fin_transaction_signature(asset_id)
        cache_key = (
            f"finance:asset-history:v4:{asset_id}:{limit}:"
            f"{tx_sig['tx_count']}:{tx_sig['max_id']}:{tx_sig['max_tx_date']}"
        )
        cached = cache.get(cache_key)
        if cached:
            return jsonify(cached)
        payload = repo.get_fin_asset_history(asset_id, limit)
        cache.set(cache_key, payload, FINANCE_CACHE_TTLS["asset_history"])
        return jsonify(payload)

    @app.get("/api/finance/portfolio-history")
    @limiter.limit("30/minute")
    def finance_portfolio_history():
        limit = min(3650, max(1, int(request.args.get("limit", "90"))))
        tx_sig = repo.get_fin_transaction_signature()
        cache_key = (
            f"finance:portfolio-history:v4:{limit}:"
            f"{tx_sig['tx_count']}:{tx_sig['max_id']}:{tx_sig['max_tx_date']}"
        )
        cached = cache.get(cache_key)
        if cached:
            return jsonify(cached)
        payload = repo.get_fin_total_history(limit)
        cache.set(cache_key, payload, FINANCE_CACHE_TTLS["portfolio_history"])
        return jsonify(payload)

    @app.get("/api/finance/benchmark-history")
    @limiter.limit("20/minute")
    def finance_benchmark_history():
        benchmark = str(request.args.get("benchmark", "ibov")).strip().lower()
        limit = min(3650, max(1, int(request.args.get("limit", "180"))))

        benchmark_yahoo_map = {
            "ibov": "%5EBVSP",
        }
        benchmark_bcb_map = {
            # SGS series IDs (percent values per period)
            "cdi": 12,
            "ipca": 433,
        }
        if benchmark not in benchmark_yahoo_map and benchmark not in benchmark_bcb_map:
            return jsonify({"error": "benchmark inválido"}), 400

        cache_key = f"finance:benchmark:{benchmark}:{limit}"
        cached = cache.get(cache_key)
        if cached:
            return jsonify(cached)

        try:
            rows: list[dict] = []

            if benchmark in benchmark_yahoo_map:
                if limit <= 30:
                    rng = "1mo"
                elif limit <= 90:
                    rng = "3mo"
                elif limit <= 180:
                    rng = "6mo"
                elif limit <= 365:
                    rng = "1y"
                elif limit <= 1825:
                    rng = "5y"
                else:
                    rng = "10y"

                y_started = time.perf_counter()
                resp = http_requests.get(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{benchmark_yahoo_map[benchmark]}",
                    params={"interval": "1d", "range": rng},
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=10,
                )
                _track_api_provider_latency(
                    "yahoo",
                    "benchmark",
                    (time.perf_counter() - y_started) * 1000,
                )
                _track_api_provider_usage("yahoo", bool(resp.ok), "benchmark")
                if not resp.ok:
                    return jsonify([])

                payload = resp.json()
                result = ((payload.get("chart") or {}).get("result") or [None])[0] or {}
                timestamps = result.get("timestamp") or []
                closes = (((result.get("indicators") or {}).get("quote") or [{}])[0]).get("close") or []

                for ts, close in zip(timestamps, closes):
                    if close is None:
                        continue
                    dt = datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d")
                    rows.append({"captured_at": dt, "price": float(close)})
            else:
                series_id = benchmark_bcb_map[benchmark]
                end_date = datetime.now(timezone.utc).date()
                start_date = end_date - timedelta(days=max(40, limit * 2))
                b_started = time.perf_counter()
                resp = http_requests.get(
                    f"https://api.bcb.gov.br/dados/serie/bcdata.sgs/{series_id}/dados",
                    params={
                        "formato": "json",
                        "dataInicial": start_date.strftime("%d/%m/%Y"),
                        "dataFinal": end_date.strftime("%d/%m/%Y"),
                    },
                    timeout=10,
                )
                _track_api_provider_latency(
                    "bcb",
                    "benchmark",
                    (time.perf_counter() - b_started) * 1000,
                )
                _track_api_provider_usage("bcb", bool(resp.ok), "benchmark")
                if not resp.ok:
                    return jsonify([])

                points = resp.json() or []
                level = 100.0
                for point in points:
                    raw_date = str(point.get("data") or "").strip()
                    raw_val = str(point.get("valor") or "").replace(",", ".").strip()
                    if not raw_date or not raw_val:
                        continue
                    try:
                        dt = datetime.strptime(raw_date, "%d/%m/%Y").strftime("%Y-%m-%d")
                        pct = float(raw_val)
                    except Exception:
                        continue
                    level *= (1.0 + (pct / 100.0))
                    rows.append({"captured_at": dt, "price": float(level)})

            if not rows:
                return jsonify([])

            rows = rows[-limit:]
            base = rows[0]["price"] or 1.0
            normalized = [
                {
                    "captured_at": r["captured_at"],
                    "price": r["price"],
                    "normalized_pct": round(((r["price"] / base) - 1.0) * 100.0, 4),
                }
                for r in rows
            ]
            cache.set(cache_key, normalized, FINANCE_CACHE_TTLS["benchmark"])
            return jsonify(normalized)
        except Exception as exc:
            logger.warning("benchmark history fetch failed (%s): %s", benchmark, exc)
            return jsonify([])

    @app.get("/api/finance/invested-history")
    @limiter.limit("30/minute")
    def finance_invested_history():
        limit = min(3650, max(1, int(request.args.get("limit", "180"))))
        asset_id = request.args.get("asset_id", type=int)
        tx_sig = repo.get_fin_transaction_signature(asset_id)
        cache_key = (
            f"finance:invested-history:v2:{asset_id or 'all'}:{limit}:"
            f"{tx_sig['tx_count']}:{tx_sig['max_id']}:{tx_sig['max_tx_date']}"
        )
        cached = cache.get(cache_key)
        if cached:
            return jsonify(cached)

        txs = repo.list_fin_transactions(asset_id=asset_id, limit=5000)
        if not txs:
            return jsonify([])

        daily_delta: dict[str, float] = {}
        for tx in sorted(txs, key=lambda x: str(x.get("tx_date") or "")):
            date_key = str(tx.get("tx_date") or "")[:10]
            if not date_key:
                continue
            tx_type = str(tx.get("tx_type") or "buy").lower()
            total = float(tx.get("total") or 0)
            signal = 1.0 if tx_type == "buy" else -1.0
            daily_delta[date_key] = float(daily_delta.get(date_key, 0.0)) + (signal * total)

        if not daily_delta:
            return jsonify([])

        cumulative = 0.0
        rows: list[dict] = []
        for date_key in sorted(daily_delta.keys()):
            cumulative += float(daily_delta[date_key])
            rows.append({"captured_at": date_key, "price": round(cumulative, 2)})

        payload = rows[-limit:]
        cache.set(cache_key, payload, FINANCE_CACHE_TTLS["invested_history"])
        return jsonify(payload)

    @app.get("/api/finance/metrics/performance")
    @limiter.limit("20/minute")
    def finance_performance_metrics():
        cached = cache.get("finance:performance:metrics")
        if cached:
            return jsonify(cached)
        txs = repo.list_fin_transactions(limit=5000)
        portfolio = repo.get_fin_portfolio()
        current_value = sum((p.get("current_price") or 0) * p.get("quantity", 0) for p in portfolio)
        invested = sum(p.get("total_invested", 0) for p in portfolio)
        simple_return = ((current_value / invested) - 1) * 100 if invested > 0 else 0.0

        cashflows: dict[str, float] = {}
        for t in txs:
            date_key = str(t.get("tx_date") or "")[:10]
            if not date_key:
                continue
            signal = -1.0 if str(t.get("tx_type") or "buy").lower() == "buy" else 1.0
            cashflows[date_key] = float(cashflows.get(date_key, 0.0)) + signal * float(t.get("total") or 0)
        today_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cashflows[today_key] = float(cashflows.get(today_key, 0.0)) + float(current_value)

        flows = [(k, v) for k, v in sorted(cashflows.items()) if abs(v) > 1e-9]
        irr = None
        if len(flows) >= 2:
            base = datetime.strptime(flows[0][0], "%Y-%m-%d")
            timed = [((datetime.strptime(d, "%Y-%m-%d") - base).days / 365.0, v) for d, v in flows]
            r = 0.1
            for _ in range(50):
                f = 0.0
                df = 0.0
                for years, cf in timed:
                    den = (1 + r) ** years
                    f += cf / den
                    df += -years * cf / ((1 + r) ** (years + 1))
                if abs(df) < 1e-12:
                    break
                nr = r - (f / df)
                if not math.isfinite(nr):
                    break
                if abs(nr - r) < 1e-9:
                    r = nr
                    break
                r = nr
            if math.isfinite(r) and r > -0.999:
                irr = r * 100

        payload = {
            "current_value": round(float(current_value), 2),
            "invested": round(float(invested), 2),
            "simple_return_pct": round(float(simple_return), 2),
            "irr_pct": round(float(irr), 2) if irr is not None else None,
            "cashflow_points": len(flows),
        }
        cache.set(
            "finance:performance:metrics",
            payload,
            FINANCE_CACHE_TTLS["performance"],
        )
        return jsonify(payload)

    @app.get("/api/finance/audit")
    @limiter.limit("20/minute")
    @require_finance_key
    def finance_audit_logs():
        limit = min(300, max(1, int(request.args.get("limit", "100"))))
        target_type = sanitize_text(
            str(request.args.get("target_type", "")),
            40,
        ).strip().lower()
        action = sanitize_text(str(request.args.get("action", "")), 40).strip().lower()
        target_id = request.args.get("target_id", type=int)

        cache_key = f"finance:audit:{limit}:{target_type}:{action}:{target_id or ''}"
        cached = cache.get(cache_key)
        if cached:
            return jsonify(cached)

        payload = repo.list_fin_audit_logs(limit)
        if target_type:
            payload = [row for row in payload if str(row.get("target_type") or "").lower() == target_type]
        if action:
            payload = [row for row in payload if str(row.get("action") or "").lower() == action]
        if target_id is not None:
            payload = [row for row in payload if int(row.get("target_id") or 0) == int(target_id)]

        cache.set(cache_key, payload, FINANCE_CACHE_TTLS["audit"])
        return jsonify(payload)

    # ── Export Data ─────────────────────────────────────────

    @app.get("/api/finance/export")
    @limiter.limit("5/minute")
    def finance_export():
        """Export portfolio + transactions as CSV or Excel."""
        fmt = request.args.get("format", "csv")
        export_type = request.args.get("type", "all")

        portfolio = repo.get_fin_portfolio()
        transactions = repo.list_fin_transactions(limit=5000)
        dividends = repo.list_fin_dividends()

        if fmt == "xlsx":
            import openpyxl

            wb = openpyxl.Workbook()

            # Portfolio sheet
            if export_type in ("all", "portfolio"):
                ws = wb.active
                ws.title = "Portfólio"
                ws.append([
                    "Símbolo", "Nome", "Tipo", "Quantidade",
                    "Preço Médio", "Preço Atual", "Total Investido",
                    "Valor Atual", "P&L", "P&L %",
                ])
                for p in portfolio:
                    current_val = (p.get("current_price") or 0) * p.get("quantity", 0)
                    pnl = current_val - p.get("total_invested", 0)
                    pnl_pct = (
                        (pnl / p["total_invested"] * 100)
                        if p["total_invested"] else 0
                    )
                    ws.append([
                        p["symbol"], p.get("name", ""), p.get("asset_type", ""),
                        p["quantity"], p["avg_price"],
                        p.get("current_price", 0), p["total_invested"],
                        round(current_val, 2), round(pnl, 2),
                        round(pnl_pct, 2),
                    ])

            # Transactions sheet
            if export_type in ("all", "transactions"):
                ws2 = wb.create_sheet("Transações")
                ws2.append([
                    "Data", "Tipo", "Símbolo", "Quantidade",
                    "Preço", "Total", "Taxas", "Notas",
                ])
                for t in transactions:
                    ws2.append([
                        (t.get("tx_date") or "")[:10],
                        t["tx_type"].upper(), t["symbol"],
                        t["quantity"], t["price"], t["total"],
                        t.get("fees", 0), t.get("notes", ""),
                    ])

            # Dividends sheet
            if export_type in ("all", "dividends") and dividends:
                ws3 = wb.create_sheet("Dividendos")
                ws3.append([
                    "Data", "Símbolo", "Tipo", "Valor/Ação",
                    "Quantidade", "Total", "Notas",
                ])
                for d in dividends:
                    ws3.append([
                        (d.get("pay_date") or "")[:10],
                        d.get("symbol", ""), d.get("div_type", ""),
                        d.get("amount_per_share", 0),
                        d.get("quantity", 0),
                        d.get("total_amount", 0),
                        d.get("notes", ""),
                    ])

            buf = io.BytesIO()
            wb.save(buf)
            buf.seek(0)
            return (
                buf.getvalue(),
                200,
                {
                    "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "Content-Disposition": "attachment; filename=financeiro.xlsx",
                },
            )

        # CSV default
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")
        writer.writerow([
            "Tipo", "Data", "Símbolo", "Nome", "Classe",
            "Quantidade", "Preço", "Total", "Taxas", "Notas",
        ])
        for t in transactions:
            writer.writerow([
                t["tx_type"].upper(),
                (t.get("tx_date") or "")[:10],
                t["symbol"], t.get("name", ""), t.get("asset_type", ""),
                t["quantity"], t["price"], t["total"],
                t.get("fees", 0), t.get("notes", ""),
            ])
        for d in dividends:
            writer.writerow([
                d.get("div_type", "DIVIDEND").upper(),
                (d.get("pay_date") or "")[:10],
                d.get("symbol", ""), d.get("asset_name", ""), "",
                d.get("quantity", 0), d.get("amount_per_share", 0),
                d.get("total_amount", 0), 0, d.get("notes", ""),
            ])
        return (
            output.getvalue(),
            200,
            {
                "Content-Type": "text/csv; charset=utf-8",
                "Content-Disposition": "attachment; filename=financeiro.csv",
            },
        )

    # ── Allocation Targets ──────────────────────────────────

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
        for t in body["targets"]:
            asset_type = sanitize_text(str(t.get("asset_type", "")), 20)
            target_pct = float(t.get("target_pct", 0))
            if asset_type:
                repo.upsert_fin_allocation_target(asset_type, target_pct)
        _invalidate_cache_prefixes("finance:allocation-targets")
        return jsonify({"ok": True})

    # ── Rebalancing Suggestion ──────────────────────────────

    @app.get("/api/finance/rebalance")
    @limiter.limit("15/minute")
    def finance_rebalance():
        """Calculate rebalancing suggestions."""
        summary = repo.get_fin_summary()
        targets = repo.list_fin_allocation_targets()
        total_value = summary["current_value"]
        aporte = max(0.0, float(request.args.get("aporte", 0) or 0))
        total_after_aporte = total_value + aporte

        if not targets or total_value <= 0:
            return jsonify({
                "suggestions": [],
                "message": "Configure suas metas de alocação primeiro.",
                "total_value": total_value,
                "aporte": aporte,
                "total_after_aporte": total_after_aporte,
            })

        target_map = {t["asset_type"]: t["target_pct"] for t in targets}
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
            suggestions.append({
                "asset_type": asset_type,
                "target_pct": round(target_pct, 1),
                "current_pct": round(current_pct, 1),
                "current_value": round(current_val, 2),
                "target_value": round(target_val, 2),
                "diff_value": round(diff_val, 2),
                "diff_pct": round(diff_pct, 1),
                "action": "comprar" if diff_val > 0 else "vender" if diff_val < 0 else "ok",
                "aporte_sugerido": 0.0,
            })

        if aporte > 0 and positive_gaps:
            total_gap = sum(float(g["gap"]) for g in positive_gaps) or 1.0
            allocation_map: dict[str, float] = {}
            for g in positive_gaps:
                allocation_map[str(g["asset_type"])] = round(
                    aporte * (float(g["gap"]) / total_gap),
                    2,
                )
            for s in suggestions:
                s["aporte_sugerido"] = allocation_map.get(s["asset_type"], 0.0)

        return jsonify({
            "suggestions": suggestions,
            "total_value": total_value,
            "aporte": aporte,
            "total_after_aporte": total_after_aporte,
        })

    @app.get("/api/finance/projection")
    @limiter.limit("20/minute")
    def finance_projection():
        """Simple patrimony projection with conservative/base/optimistic scenarios."""
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

        return jsonify({
            "current_value": round(current_value, 2),
            "months": months,
            "aporte_mensal": aporte_mensal,
            "scenarios": result,
        })

    @app.get("/api/finance/dividend-ceiling")
    @limiter.limit("20/minute")
    def finance_dividend_ceiling():
        """Estimate ceiling price by target DY using trailing dividends."""
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

        # Use trailing dividends by symbol for selected period.
        dividends = repo.list_fin_dividends(limit=5000)
        cutoff = datetime.now().replace(day=1)
        cutoff_month = cutoff.month - (months - 1)
        cutoff_year = cutoff.year
        while cutoff_month <= 0:
            cutoff_month += 12
            cutoff_year -= 1
        cutoff_key = f"{cutoff_year}-{str(cutoff_month).zfill(2)}"

        div_per_symbol: dict[str, float] = {}
        for d in dividends:
            symbol = str(d.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            pay_key = str(d.get("pay_date") or d.get("ex_date") or "")[:7]
            if pay_key and pay_key < cutoff_key:
                continue
            div_per_symbol[symbol] = (
                float(div_per_symbol.get(symbol, 0.0))
                + float(d.get("total_amount") or 0.0)
            )

        rows = []
        for p in portfolio:
            symbol = str(p.get("symbol") or "").strip().upper()
            qty = float(p.get("quantity") or 0.0)
            current_price = float(p.get("current_price") or 0.0)
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

            rows.append({
                "symbol": symbol,
                "asset_type": p.get("asset_type") or "",
                "current_price": round(current_price, 4),
                "dps_ttm": round(dps_ttm, 4),
                "ceiling_price": round(ceiling_price, 4),
                "implied_dy": round(implied_dy, 2),
                "upside_pct": round(float(upside), 2) if upside is not None else None,
                "signal": signal,
            })

        rows.sort(key=lambda r: (r.get("signal") != "atrativo", -(r.get("upside_pct") or -9999)))
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
        """Project time-to-goal for financial independence by scenarios."""
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

    # ── IR Report ───────────────────────────────────────────

    @app.get("/api/finance/ir-report")
    @limiter.limit("10/minute")
    def finance_ir_report():
        year = request.args.get("year", datetime.now().year, type=int)
        report = repo.get_fin_ir_report(year)
        return jsonify(report)

    # ── Market Data (brapi.dev for BR stocks, CoinGecko for crypto) ──

    @app.get("/api/finance/market-data")
    @limiter.limit("10/minute")
    def finance_market_data():
        """Fetch live quotes for tracked assets."""
        cached = cache.get("finance:market")
        if cached:
            return jsonify(cached)

        now_iso = datetime.now(timezone.utc).isoformat()

        def _resolve_brapi_monthly_limit() -> int:
            cfg_limit = app.config.get("BRAPI_MONTHLY_LIMIT")
            if cfg_limit is None:
                cfg_limit = repo.get_setting("brapi_monthly_limit", "15000")
            try:
                parsed = int(str(cfg_limit).strip())
            except Exception:
                parsed = 15000
            return max(100, min(500000, parsed))

        def _resolve_brapi_reserve_pct() -> int:
            raw = app.config.get("BRAPI_RESERVE_PCT")
            if raw is None:
                raw = repo.get_setting("brapi_reserve_pct", "15")
            try:
                parsed = int(str(raw).strip())
            except Exception:
                parsed = 15
            return max(0, min(50, parsed))

        def _resolve_brapi_max_calls_per_request() -> int:
            raw = app.config.get("BRAPI_MAX_CALLS_PER_REQUEST")
            if raw is None:
                raw = repo.get_setting("brapi_max_calls_per_request", "2")
            try:
                parsed = int(str(raw).strip())
            except Exception:
                parsed = 2
            return max(0, min(200, parsed))

        brapi_month_key = datetime.now(timezone.utc).strftime("%Y%m")
        brapi_usage_key = f"brapi_usage:{brapi_month_key}"
        try:
            brapi_usage_start = int(repo.get_setting(brapi_usage_key, "0") or 0)
        except Exception:
            brapi_usage_start = 0
        brapi_limit = _resolve_brapi_monthly_limit()
        brapi_reserve_pct = _resolve_brapi_reserve_pct()
        brapi_reserve_calls = int(math.ceil(brapi_limit * (brapi_reserve_pct / 100.0)))
        brapi_usable_limit = max(0, brapi_limit - brapi_reserve_calls)
        brapi_max_calls_per_request = _resolve_brapi_max_calls_per_request()
        brapi_usage_delta = 0
        brapi_lock = Lock()

        def _try_reserve_brapi_call() -> bool:
            nonlocal brapi_usage_delta
            with brapi_lock:
                if brapi_usage_delta >= brapi_max_calls_per_request:
                    return False
                if brapi_usage_start + brapi_usage_delta >= brapi_usable_limit:
                    return False
                brapi_usage_delta += 1
                return True

        assets = repo.list_fin_assets()
        watchlist = repo.list_fin_watchlist()

        # Collect all symbols by type
        stock_symbols = set()
        crypto_ids = set()
        for item in assets + watchlist:
            sym = item.get("symbol", "")
            atype = item.get("asset_type", "stock")
            if atype == "crypto":
                crypto_ids.add(sym.lower())
            else:
                stock_symbols.add(sym)

        results: dict = {"stocks": {}, "crypto": {}, "indices": {}, "meta": {}}

        def _fetch_stocks():
            """Fetch BR stock data from brapi.dev."""
            if not stock_symbols:
                return

            def _save_stock_quote(
                sym: str,
                name: str,
                price: float | None,
                previous_close: float | None,
                change: float | None,
                change_pct: float | None,
                volume: float | None,
                market_cap: float | None,
                high: float | None,
                low: float | None,
                updated: float | None = None,
                source: str = "unknown",
                is_stale: bool = False,
                captured_at: str | None = None,
                latency_ms: float | None = None,
            ) -> None:
                results["stocks"][sym] = {
                    "symbol": sym,
                    "name": name,
                    "price": price,
                    "previous_close": previous_close,
                    "change": change,
                    "change_pct": change_pct,
                    "volume": volume,
                    "market_cap": market_cap,
                    "high": high,
                    "low": low,
                    "updated": updated,
                    "source": source,
                    "is_stale": is_stale,
                    "captured_at": captured_at or now_iso,
                    "latency_ms": latency_ms,
                }
                _aid = repo.upsert_fin_asset({
                    "symbol": sym,
                    "name": name,
                    "asset_type": "stock",
                    "current_price": price,
                    "previous_close": previous_close,
                    "day_change": change,
                    "day_change_pct": change_pct,
                    "market_cap": market_cap,
                    "volume": volume,
                    "extra": {
                        "high": high,
                        "low": low,
                    },
                })
                if _aid and price:
                    repo.record_fin_asset_price(_aid, price, volume)

            brapi_token = str(app.config.get("BRAPI_TOKEN", "")).strip()
            if not brapi_token:
                brapi_token = repo.get_setting("brapi_token", "").strip()
                if brapi_token:
                    app.config["BRAPI_TOKEN"] = brapi_token

            for sym in sorted(stock_symbols):
                if not sym or sym.startswith("^"):
                    continue

                loaded = False

                # 1) Yahoo first to preserve brapi monthly quota.
                try:
                    y_started = time.perf_counter()
                    yresp = _http_get_with_retry(
                        "https://query1.finance.yahoo.com/v7/finance/quote",
                        params={"symbols": f"{sym}.SA"},
                        timeout=10,
                    )
                    y_latency_ms = round((time.perf_counter() - y_started) * 1000, 1)
                    _track_api_provider_latency("yahoo", "market-data", y_latency_ms)
                    _track_api_provider_usage("yahoo", bool(yresp.ok), "market-data")
                    if yresp.ok:
                        ydata = yresp.json()
                        items = ydata.get("quoteResponse", {}).get("result", [])
                        if items:
                            item = items[0]
                            price = item.get("regularMarketPrice")
                            if price is not None:
                                _save_stock_quote(
                                    sym=sym,
                                    name=item.get("longName")
                                    or item.get("shortName")
                                    or sym,
                                    price=price,
                                    previous_close=item.get(
                                        "regularMarketPreviousClose",
                                    ),
                                    change=item.get("regularMarketChange"),
                                    change_pct=item.get("regularMarketChangePercent"),
                                    volume=item.get("regularMarketVolume"),
                                    market_cap=item.get("marketCap"),
                                    high=item.get("regularMarketDayHigh"),
                                    low=item.get("regularMarketDayLow"),
                                    updated=item.get("regularMarketTime"),
                                    source="yahoo",
                                    is_stale=False,
                                    captured_at=now_iso,
                                    latency_ms=y_latency_ms,
                                )
                                loaded = True
                except Exception as exc:
                    _track_api_provider_usage("yahoo", False, "market-data")
                    logger.warning("Yahoo Finance fetch failed for %s: %s", sym, exc)

                if loaded:
                    continue

                # 2) brapi fallback only if quota/token available.
                if not brapi_token:
                    continue
                if not _try_reserve_brapi_call():
                    continue
                try:
                    params = {"fundamental": "true", "token": brapi_token}
                    b_started = time.perf_counter()
                    resp = _http_get_with_retry(
                        f"https://brapi.dev/api/quote/{sym}",
                        params=params,
                        timeout=10,
                    )
                    b_latency_ms = round((time.perf_counter() - b_started) * 1000, 1)
                    _track_api_provider_latency("brapi", "market-data", b_latency_ms)
                    _track_api_provider_usage("brapi", bool(resp.ok), "market-data")
                    if resp.ok:
                        data = resp.json()
                        items = data.get("results", [])
                        if not items:
                            continue
                        item = items[0]
                        price = item.get("regularMarketPrice")
                        if price is None:
                            continue
                        _save_stock_quote(
                            sym=sym,
                            name=item.get("longName", sym),
                            price=price,
                            previous_close=item.get("regularMarketPreviousClose"),
                            change=item.get("regularMarketChange"),
                            change_pct=item.get("regularMarketChangePercent"),
                            volume=item.get("regularMarketVolume"),
                            market_cap=item.get("marketCap"),
                            high=item.get("regularMarketDayHigh"),
                            low=item.get("regularMarketDayLow"),
                            updated=item.get("regularMarketTime"),
                            source="brapi",
                            is_stale=False,
                            captured_at=now_iso,
                            latency_ms=b_latency_ms,
                        )
                        _track_api_provider_fallback("brapi", "market-data")
                        loaded = True
                except Exception as exc:
                    _track_api_provider_usage("brapi", False, "market-data")
                    logger.warning("brapi.dev fetch failed for %s: %s", sym, exc)

                if loaded:
                    continue

                # 3) DB fallback — use last known price saved in fin_assets.
                db_asset = repo.get_fin_asset_by_symbol(sym)
                if db_asset and db_asset.get("current_price") is not None:
                    stale_price = float(db_asset["current_price"])
                    _track_api_provider_usage("db-fallback", True, "market-data")
                    _track_api_provider_fallback("db-fallback", "market-data")
                    results["stocks"][sym] = {
                        "symbol": sym,
                        "name": db_asset.get("name") or sym,
                        "price": stale_price,
                        "previous_close": db_asset.get("previous_close"),
                        "change": db_asset.get("day_change"),
                        "change_pct": db_asset.get("day_change_pct"),
                        "volume": db_asset.get("volume"),
                        "market_cap": db_asset.get("market_cap"),
                        "high": None,
                        "low": None,
                        "updated": None,
                        "stale": True,
                        "source": "db-fallback",
                        "is_stale": True,
                        "captured_at": db_asset.get("updated_at") or now_iso,
                        "latency_ms": None,
                    }
                    logger.info(
                        "DB fallback price used for %s: %.4f (stale)",
                        sym, stale_price,
                    )

        def _fetch_crypto():
            """Fetch crypto from CoinGecko."""
            if not crypto_ids:
                return
            try:
                ids_param = ",".join(crypto_ids)
                c_started = time.perf_counter()
                resp = _http_get_with_retry(
                    "https://api.coingecko.com/api/v3/simple/price",
                    params={
                        "ids": ids_param,
                        "vs_currencies": "brl,usd",
                        "include_24hr_change": "true",
                        "include_market_cap": "true",
                        "include_24hr_vol": "true",
                    },
                    timeout=10,
                )
                c_latency_ms = round((time.perf_counter() - c_started) * 1000, 1)
                _track_api_provider_latency(
                    "coingecko",
                    "market-data",
                    c_latency_ms,
                )
                _track_api_provider_usage("coingecko", bool(resp.ok), "market-data")
                if resp.ok:
                    data = resp.json()
                    for cid, info in data.items():
                        results["crypto"][cid] = {
                            "id": cid,
                            "price_brl": info.get("brl"),
                            "price_usd": info.get("usd"),
                            "change_24h": info.get("brl_24h_change"),
                            "market_cap": info.get("brl_market_cap"),
                            "volume_24h": info.get("brl_24h_vol"),
                            "source": "coingecko",
                            "is_stale": False,
                            "captured_at": now_iso,
                            "latency_ms": c_latency_ms,
                        }
                        _aid = repo.upsert_fin_asset({
                            "symbol": cid.upper(),
                            "name": cid.title(),
                            "asset_type": "crypto",
                            "currency": "BRL",
                            "current_price": info.get("brl"),
                            "day_change_pct": info.get("brl_24h_change"),
                            "market_cap": info.get("brl_market_cap"),
                            "volume": info.get("brl_24h_vol"),
                        })
                        _cprice = info.get("brl")
                        if _aid and _cprice:
                            repo.record_fin_asset_price(
                                _aid, _cprice,
                                info.get("brl_24h_vol"),
                            )
            except Exception as exc:
                _track_api_provider_usage("coingecko", False, "market-data")
                logger.warning("CoinGecko fetch failed: %s", exc)

        def _fetch_indices():
            """Fetch market indices via Yahoo first and brapi fallback for IBOV."""
            _INDEX_SYMBOLS = {
                "^BVSP": "Ibovespa",
                "^GSPC": "S&P 500",
                "^IXIC": "Nasdaq",
                "USDBRL=X": "Dólar (BRL)",
            }

            # Yahoo Finance v8 chart fallback — fetch all in parallel
            def _yahoo_index(yahoo_sym: str, default_name: str) -> None:
                try:
                    y_started = time.perf_counter()
                    yresp = _http_get_with_retry(
                        f"https://query2.finance.yahoo.com/v8/finance/chart/{yahoo_sym}",
                        params={"interval": "1d", "range": "1d"},
                        headers={"User-Agent": "Mozilla/5.0"},
                        timeout=8,
                    )
                    y_latency_ms = round((time.perf_counter() - y_started) * 1000, 1)
                    _track_api_provider_latency(
                        "yahoo",
                        "market-data",
                        y_latency_ms,
                    )
                    _track_api_provider_usage("yahoo", bool(yresp.ok), "market-data")
                    if not yresp.ok:
                        return
                    chart = yresp.json().get("chart", {}).get("result", [])
                    if not chart:
                        return
                    meta = chart[0].get("meta", {})
                    price = meta.get("regularMarketPrice")
                    prev_close = meta.get("chartPreviousClose") or meta.get(
                        "previousClose",
                    )
                    change = (
                        round(price - prev_close, 4)
                        if price is not None and prev_close
                        else None
                    )
                    change_pct = (
                        round(change / prev_close * 100, 4)
                        if change is not None and prev_close
                        else None
                    )
                    results["indices"][yahoo_sym] = {
                        "name": meta.get("longName")
                        or meta.get("shortName")
                        or default_name,
                        "price": price,
                        "change": change,
                        "change_pct": change_pct,
                        "source": "yahoo",
                        "is_stale": False,
                        "captured_at": now_iso,
                        "latency_ms": y_latency_ms,
                    }
                except Exception as exc:
                    _track_api_provider_usage("yahoo", False, "market-data")
                    logger.warning(
                        "Yahoo indices fetch failed for %s: %s", yahoo_sym, exc,
                    )

            with ThreadPoolExecutor(max_workers=4) as idx_executor:
                idx_futures = [
                    idx_executor.submit(_yahoo_index, sym, name)
                    for sym, name in _INDEX_SYMBOLS.items()
                ]
                for f in as_completed(idx_futures):
                    f.result()

            # brapi fallback only for IBOV when Yahoo is unavailable.
            if "^BVSP" in results["indices"]:
                return
            brapi_token = str(app.config.get("BRAPI_TOKEN", "")).strip()
            if not brapi_token:
                brapi_token = repo.get_setting("brapi_token", "").strip()
            if not brapi_token:
                return
            if not _try_reserve_brapi_call():
                return
            try:
                b_started = time.perf_counter()
                resp = _http_get_with_retry(
                    "https://brapi.dev/api/quote/%5EBVSP",
                    params={"token": brapi_token},
                    timeout=8,
                )
                b_latency_ms = round((time.perf_counter() - b_started) * 1000, 1)
                _track_api_provider_latency(
                    "brapi",
                    "market-data",
                    b_latency_ms,
                )
                _track_api_provider_usage("brapi", bool(resp.ok), "market-data")
                if resp.ok:
                    data = resp.json()
                    items = data.get("results", [])
                    if items:
                        item = items[0]
                        results["indices"]["^BVSP"] = {
                            "name": item.get("longName", "Ibovespa"),
                            "price": item.get("regularMarketPrice"),
                            "change": item.get("regularMarketChange"),
                            "change_pct": item.get("regularMarketChangePercent"),
                            "source": "brapi",
                            "is_stale": False,
                            "captured_at": now_iso,
                            "latency_ms": b_latency_ms,
                        }
                        _track_api_provider_fallback("brapi", "market-data")
            except Exception as exc:
                _track_api_provider_usage("brapi", False, "market-data")
                logger.warning("brapi indices fetch failed: %s", exc)

        # Run all fetches in parallel
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(_fetch_stocks),
                executor.submit(_fetch_crypto),
                executor.submit(_fetch_indices),
            ]
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception as exc:
                    logger.warning("market-data worker failed: %s", exc)

        if brapi_usage_delta > 0:
            final_usage = brapi_usage_start + brapi_usage_delta
            repo.set_setting(brapi_usage_key, str(final_usage))
        else:
            final_usage = brapi_usage_start

        remaining = max(0, brapi_limit - final_usage)
        results["meta"]["brapi"] = {
            "month": brapi_month_key,
            "usage": final_usage,
            "limit": brapi_limit,
            "reserve_pct": brapi_reserve_pct,
            "reserve_calls": brapi_reserve_calls,
            "usable_limit": brapi_usable_limit,
            "remaining_usable": max(0, brapi_usable_limit - final_usage),
            "per_request_cap": brapi_max_calls_per_request,
            "request_brapi_calls": brapi_usage_delta,
            "remaining": remaining,
            "degraded": final_usage >= brapi_usable_limit,
        }

        stale_stocks = sum(1 for q in results["stocks"].values() if q.get("is_stale"))
        stale_crypto = sum(1 for q in results["crypto"].values() if q.get("is_stale"))
        stale_indices = sum(1 for q in results["indices"].values() if q.get("is_stale"))
        stale_items = stale_stocks + stale_crypto + stale_indices
        results["meta"]["quality"] = {
            "captured_at": now_iso,
            "has_stale_data": stale_items > 0,
            "stale_items": stale_items,
            "stale_stocks": stale_stocks,
            "stale_crypto": stale_crypto,
            "stale_indices": stale_indices,
        }

        cache.set("finance:market", results, FINANCE_CACHE_TTLS["market"])
        return jsonify(results)

    # ── AI Financial Analysis ───────────────────────────────

    @app.post("/api/finance/ai-analysis")
    @limiter.limit("6/minute")
    @require_finance_key
    def finance_ai_analysis():
        """AI-powered financial analysis."""
        if not app.config.get("AI_LOCAL_ENABLED"):
            return jsonify({"error": "IA local não habilitada"}), 503

        body = request.get_json(silent=True) or {}
        user_msg = sanitize_text(
            str(body.get("message", "Analise meu portfólio")), 500,
        )
        analysis_type = str(body.get("type", "general"))

        # Build financial context
        summary = repo.get_fin_summary()
        currency = repo.list_currency_rates()
        goals = repo.list_fin_goals()
        transactions = repo.list_fin_transactions(limit=20)

        ctx_parts = []

        # Portfolio summary
        ctx_parts.append(
            f"Portfólio: valor total R${summary['current_value']:,.2f}, "
            f"investido R${summary['total_invested']:,.2f}, "
            f"P&L R${summary['total_pnl']:,.2f} ({summary['total_pnl_pct']:.1f}%)"
        )

        # Holdings
        for p in summary.get("portfolio", [])[:15]:
            current = (p.get("current_price") or 0) * p.get("quantity", 0)
            pnl = current - p.get("total_invested", 0)
            ctx_parts.append(
                f"  - {p['symbol']}: {p['quantity']:.2f} un × "
                f"R${p.get('current_price', 0):.2f} = R${current:,.2f} "
                f"(P&L R${pnl:,.2f})"
            )

        # Allocation
        alloc = summary.get("allocation", {})
        if alloc:
            parts = [f"{k}: R${v:,.2f}" for k, v in alloc.items()]
            ctx_parts.append(f"Alocação: {', '.join(parts)}")

        # Currency
        for c in currency:
            ctx_parts.append(
                f"Câmbio {c['pair']}: R${c['rate']:.4f} ({c.get('variation', 0):+.2f}%)"
            )

        # Goals
        for g in goals[:5]:
            pct = (
                (g["current_amount"] / g["target_amount"] * 100)
                if g["target_amount"] else 0
            )
            ctx_parts.append(
                f"Meta '{g['name']}': R${g['current_amount']:,.2f} / "
                f"R${g['target_amount']:,.2f} ({pct:.0f}%)"
            )

        # Recent transactions
        if transactions:
            tx_summary = []
            for t in transactions[:10]:
                tx_summary.append(
                    f"{t['tx_type'].upper()} {t['symbol']} "
                    f"{t['quantity']:.2f}×R${t['price']:.2f}"
                )
            ctx_parts.append(
                f"Últimas transações: {'; '.join(tx_summary)}"
            )

        system_prompt = (
            "Você é um consultor financeiro pessoal especializado no mercado brasileiro. "
            "Analise os dados financeiros do usuário e responda em português de forma clara e objetiva. "
            "Inclua análises de risco, diversificação, tendências e recomendações quando relevante. "
            "Use formatação markdown para organizar a resposta.\n\n"
            "Dados financeiros atuais:\n" + "\n".join(ctx_parts)
        )

        if analysis_type == "risk":
            system_prompt += (
                "\n\nFoco: análise detalhada de riscos, "
                "concentração, exposição setorial e volatilidade."
            )
        elif analysis_type == "allocation":
            system_prompt += (
                "\n\nFoco: análise de diversificação e alocação. "
                "Sugira rebalanceamento se necessário."
            )
        elif analysis_type == "performance":
            system_prompt += (
                "\n\nFoco: análise de performance, comparar com "
                "benchmarks como IBOV, CDI, IPCA."
            )

        try:
            ai_url = app.config["AI_LOCAL_URL"].rstrip("/")
            endpoint = app.config.get(
                "AI_LOCAL_LLAMA_CPP_CHAT_ENDPOINT",
                "/v1/chat/completions",
            )
            timeout_s = max(
                90,
                int(app.config.get("AI_LOCAL_TIMEOUT_SECONDS", 30)),
            )
            resp = http_requests.post(
                f"{ai_url}{endpoint}",
                json={
                    "model": app.config.get(
                        "AI_LOCAL_MODEL", "qwen2.5:7b-instruct",
                    ),
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_msg},
                    ],
                    "max_tokens": 600,
                    "temperature": 0.7,
                },
                timeout=timeout_s,
            )
            if resp.ok:
                data = resp.json()
                choices = data.get("choices", [])
                answer = (
                    choices[0]["message"]["content"]
                    if choices else "Sem resposta"
                )
                return jsonify({"answer": answer, "type": analysis_type})
            return jsonify({
                "error": f"AI retornou {resp.status_code}",
            }), 502
        except Exception as exc:
            logger.warning("Finance AI analysis failed: %s", exc)
            return jsonify({"error": str(exc)}), 502

    # ── AI Chat Financeiro (com auto-cadastro) ────────────

    def _execute_ai_actions(
        actions: list[dict],
    ) -> list[dict]:
        """Execute structured actions returned by AI."""
        results: list[dict] = []
        for act in actions:
            act_type = act.get("action", "")
            try:
                if act_type == "add_asset":
                    symbol = sanitize_text(
                        str(act.get("symbol", "")).upper().strip(), 20,
                    )
                    if not symbol:
                        continue
                    aid = repo.upsert_fin_asset({
                        "symbol": symbol,
                        "name": sanitize_text(
                            str(act.get("name", symbol)), 100,
                        ),
                        "asset_type": _parse_asset_type(
                            str(act.get("asset_type", "stock")),
                        ),
                        "currency": sanitize_text(
                            str(act.get("currency", "BRL")).upper(), 10,
                        ),
                    })
                    results.append({
                        "action": "add_asset",
                        "symbol": symbol,
                        "id": aid,
                        "ok": True,
                    })

                elif act_type in ("add_transaction", "buy", "sell"):
                    symbol = sanitize_text(
                        str(act.get("symbol", "")).upper().strip(), 20,
                    )
                    if not symbol:
                        continue
                    # Ensure asset exists
                    asset = repo.get_fin_asset_by_symbol(symbol)
                    if not asset:
                        aid = repo.upsert_fin_asset({
                            "symbol": symbol,
                            "name": sanitize_text(
                                str(act.get("name", symbol)), 100,
                            ),
                            "asset_type": _parse_asset_type(
                                str(act.get("asset_type", "stock")),
                            ),
                            "currency": "BRL",
                        })
                    else:
                        aid = asset["id"]

                    qty = float(act.get("quantity", 0))
                    price = float(act.get("price", 0))
                    fees = float(act.get("fees", 0))
                    if qty <= 0 or price <= 0:
                        results.append({
                            "action": act_type,
                            "symbol": symbol,
                            "ok": False,
                            "error": "quantidade e preço obrigatórios",
                        })
                        continue

                    tx_type = "sell" if act_type == "sell" else (
                        _parse_tx_type(str(act.get("tx_type", "buy")))
                    )
                    tx_date = str(act.get("date", "")) or (
                        datetime.now().strftime("%Y-%m-%d")
                    )
                    total = qty * price + fees

                    tx_id = repo.add_fin_transaction({
                        "asset_id": aid,
                        "tx_type": tx_type,
                        "quantity": qty,
                        "price": price,
                        "total": total,
                        "fees": fees,
                        "notes": sanitize_text(
                            str(act.get("notes", "Via IA")), 500,
                        ),
                        "tx_date": tx_date,
                    })
                    _recalc_portfolio(repo, aid)
                    results.append({
                        "action": "add_transaction",
                        "symbol": symbol,
                        "tx_type": tx_type,
                        "quantity": qty,
                        "price": price,
                        "tx_id": tx_id,
                        "ok": True,
                    })

                elif act_type == "add_watchlist":
                    symbol = sanitize_text(
                        str(act.get("symbol", "")).upper().strip(), 20,
                    )
                    if not symbol:
                        continue
                    wid = repo.add_fin_watchlist({
                        "symbol": symbol,
                        "name": sanitize_text(
                            str(act.get("name", symbol)), 100,
                        ),
                        "asset_type": _parse_asset_type(
                            str(act.get("asset_type", "stock")),
                        ),
                        "target_price": (
                            float(act["target_price"])
                            if act.get("target_price") else None
                        ),
                        "alert_above": bool(act.get("alert_above")),
                        "notes": sanitize_text(
                            str(act.get("notes", "")), 500,
                        ),
                    })
                    results.append({
                        "action": "add_watchlist",
                        "symbol": symbol,
                        "id": wid,
                        "ok": True,
                    })

                elif act_type == "add_goal":
                    name = sanitize_text(
                        str(act.get("name", "")), 100,
                    )
                    target = float(act.get("target_amount", 0))
                    if not name or target <= 0:
                        continue
                    gid = repo.add_fin_goal({
                        "name": name,
                        "target_amount": target,
                        "current_amount": float(
                            act.get("current_amount", 0),
                        ),
                        "deadline": str(act.get("deadline", "")) or None,
                        "category": sanitize_text(
                            str(act.get("category", "savings")), 30,
                        ),
                        "notes": sanitize_text(
                            str(act.get("notes", "")), 500,
                        ),
                    })
                    results.append({
                        "action": "add_goal",
                        "name": name,
                        "id": gid,
                        "ok": True,
                    })

            except Exception as exc:
                results.append({
                    "action": act_type,
                    "ok": False,
                    "error": str(exc),
                })

        if results:
            _invalidate_financial_state_cache(include_market=True, include_dividends=True)
        return results

    @app.post("/api/finance/ai-chat")
    @limiter.limit("8/minute")
    @require_finance_key
    def finance_ai_chat():
        """Open-ended financial chat with AI + auto-register."""
        if not app.config.get("AI_LOCAL_ENABLED"):
            return jsonify({"error": "IA local não habilitada"}), 503

        body = request.get_json(silent=True) or {}
        user_msg = sanitize_text(str(body.get("message", "")), 800)
        if not user_msg:
            return jsonify({"error": "message obrigatório"}), 400

        # Build context
        summary = repo.get_fin_summary()
        currency = repo.list_currency_rates()
        goals = repo.list_fin_goals()
        assets = repo.list_fin_assets()

        ctx_parts = [
            f"Portfólio: R${summary['current_value']:,.2f} "
            f"(investido R${summary['total_invested']:,.2f}, "
            f"P&L {summary['total_pnl_pct']:+.1f}%).",
        ]
        for p in summary.get("portfolio", [])[:10]:
            ctx_parts.append(
                f"  {p['symbol']}: {p['quantity']:.2f}un "
                f"× R${p.get('current_price', 0):.2f}",
            )
        for c in currency:
            ctx_parts.append(
                f"  Câmbio {c['pair']}: R${c['rate']:.2f}",
            )
        for g in goals[:5]:
            pct = (
                (g["current_amount"] / g["target_amount"] * 100)
                if g["target_amount"] else 0
            )
            ctx_parts.append(
                f"  Meta '{g['name']}': {pct:.0f}% "
                f"(R${g['current_amount']:,.2f}/R${g['target_amount']:,.2f})",
            )
        asset_symbols = [a["symbol"] for a in assets[:30]]
        if asset_symbols:
            ctx_parts.append(
                f"  Ativos cadastrados: {', '.join(asset_symbols)}",
            )

        system_prompt = (
            "Você é um assistente financeiro pessoal brasileiro inteligente. "
            "Responda sempre em português de forma clara e objetiva.\n\n"
            "IMPORTANTE: Quando o usuário pedir para REGISTRAR, CADASTRAR, COMPRAR, "
            "VENDER, ADICIONAR um ativo, transação, item na watchlist ou meta financeira, "
            "você DEVE incluir um bloco JSON de ações no início da resposta no formato:\n"
            "```actions\n"
            '[{"action": "TIPO", ...campos}]\n'
            "```\n\n"
            "Tipos de ação disponíveis:\n"
            '- {"action":"add_asset","symbol":"PETR4","name":"Petrobras PN",'
            '"asset_type":"stock","currency":"BRL"}\n'
            '- {"action":"buy","symbol":"PETR4","quantity":100,"price":35.50,'
            '"date":"2026-01-15","notes":"..."}\n'
            '- {"action":"sell","symbol":"PETR4","quantity":50,"price":40.00,'
            '"date":"2026-01-15"}\n'
            '- {"action":"add_watchlist","symbol":"VALE3","name":"Vale SA",'
            '"asset_type":"stock","target_price":68.00,"alert_above":false}\n'
            '- {"action":"add_goal","name":"Reserva de emergência",'
            '"target_amount":50000,"current_amount":10000,'
            '"deadline":"2027-01-01","category":"savings"}\n\n'
            "Regras:\n"
            "- Múltiplas ações podem ser enviadas no mesmo bloco JSON (array).\n"
            "- Sempre confirme ao usuário o que foi feito após o bloco de ações.\n"
            "- asset_type pode ser: stock, fii, etf, crypto, fund, renda-fixa\n"
            "- Se o usuário não informar o preço ou quantidade, PERGUNTE antes de criar.\n"
            "- fees (taxas/corretagem) deve ser 0 a menos que o usuário informe explicitamente.\n"
            "- Se for apenas uma pergunta/análise, NÃO inclua o bloco actions.\n"
            "- Use markdown na resposta textual.\n\n"
            "Dados financeiros atuais do usuário:\n"
            + "\n".join(ctx_parts)
        )

        try:
            ai_url = app.config["AI_LOCAL_URL"].rstrip("/")
            endpoint = app.config.get(
                "AI_LOCAL_LLAMA_CPP_CHAT_ENDPOINT",
                "/v1/chat/completions",
            )
            resp = http_requests.post(
                f"{ai_url}{endpoint}",
                json={
                    "model": app.config.get(
                        "AI_LOCAL_MODEL", "qwen2.5:7b-instruct",
                    ),
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_msg},
                    ],
                    "max_tokens": 700,
                    "temperature": 0.4,
                },
                timeout=app.config.get("AI_LOCAL_TIMEOUT_SECONDS", 45),
            )
            if not resp.ok:
                return jsonify({
                    "error": f"AI retornou {resp.status_code}",
                }), 502

            data = resp.json()
            choices = data.get("choices", [])
            raw_answer = (
                choices[0]["message"]["content"]
                if choices else "Sem resposta"
            )

            # Extract action blocks from AI response
            actions_executed: list[dict] = []
            clean_answer = raw_answer

            # Pattern: ```actions\n[...]\n```
            action_pattern = re.compile(
                r"```actions?\s*\n(.*?)\n```",
                re.DOTALL | re.IGNORECASE,
            )
            matches = action_pattern.findall(raw_answer)

            if not matches:
                # Also try inline JSON arrays [{"action":...}]
                json_pattern = re.compile(
                    r'\[\s*\{["\']action["\'].*?\}\s*\]',
                    re.DOTALL,
                )
                matches = json_pattern.findall(raw_answer)

            for match in matches:
                try:
                    parsed = json.loads(match)
                    if isinstance(parsed, dict):
                        parsed = [parsed]
                    if isinstance(parsed, list):
                        results = _execute_ai_actions(parsed)
                        actions_executed.extend(results)
                except (json.JSONDecodeError, TypeError):
                    pass

            # Remove action blocks from displayed answer
            clean_answer = action_pattern.sub("", clean_answer).strip()
            clean_answer = re.sub(
                r'\[\s*\{["\']action["\'].*?\}\s*\]',
                "",
                clean_answer,
                flags=re.DOTALL,
            ).strip()

            return jsonify({
                "answer": clean_answer,
                "actions": actions_executed,
            })

        except Exception as exc:
            return jsonify({"error": str(exc)}), 502


def _recalc_portfolio(repo: Repository, asset_id: int) -> None:
    """Recalculate portfolio position from all transactions."""
    txns = repo.list_fin_transactions(asset_id=asset_id, limit=9999)
    qty = 0.0
    total_cost = 0.0
    for t in reversed(txns):
        if t["tx_type"] == "buy":
            qty += t["quantity"]
            total_cost += t["total"]
        elif t["tx_type"] == "sell":
            if qty > 0:
                avg = total_cost / qty
                sell_qty = min(t["quantity"], qty)
                qty -= sell_qty
                total_cost -= avg * sell_qty

    if qty > 0:
        avg_price = total_cost / qty
        repo.upsert_fin_portfolio(asset_id, qty, avg_price, total_cost)
    else:
        repo.delete_fin_portfolio(asset_id)
