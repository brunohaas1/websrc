"""Finance maintenance routes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def register_maintenance_routes(app, limiter, repo, cache, logger, helpers=None) -> None:
    if helpers is None:
        helpers = {}

    _audit = helpers.get("_audit", lambda *args, **kwargs: None)
    _invalidate_financial_state_cache = helpers.get(
        "_invalidate_financial_state_cache",
        lambda **kwargs: None,
    )
    _recalc_portfolio = helpers.get("_recalc_portfolio", lambda repo_obj, asset_id: None)
    cleanup_confirm_token = helpers["CLEANUP_CONFIRM_TOKEN"]
    cleanup_cooldown_seconds = helpers["CLEANUP_COOLDOWN_SECONDS"]
    cleanup_idempotency_ttl = helpers["CLEANUP_IDEMPOTENCY_TTL"]

    from flask import jsonify, request

    from ..security import require_finance_key

    @app.post("/api/finance/maintenance/cleanup-duplicates")
    @limiter.limit("2/day")
    @require_finance_key
    def finance_cleanup_duplicate_transactions():
        confirm_token = str(request.headers.get("X-Cleanup-Confirm", "")).strip()
        if confirm_token != cleanup_confirm_token:
            return jsonify({
                "error": "Confirmação obrigatória para limpeza.",
                "required_header": "X-Cleanup-Confirm",
                "required_value": cleanup_confirm_token,
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
        if last_ts and (now_ts - last_ts) < cleanup_cooldown_seconds:
            retry_after = cleanup_cooldown_seconds - (now_ts - last_ts)
            return jsonify({
                "error": "Cleanup em cooldown. Tente novamente depois.",
                "retry_after_seconds": retry_after,
            }), 429

        tx_payload = repo.cleanup_duplicate_fin_transactions()
        div_payload = repo.cleanup_duplicate_fin_dividends()
        touched_asset_ids = [
            int(asset_id) for asset_id in tx_payload.pop("touched_asset_ids", [])
        ]
        for asset_id in touched_asset_ids:
            _recalc_portfolio(repo, asset_id)
        _invalidate_financial_state_cache(include_market=True, include_dividends=True)
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
        cache.set(idem_cache_key, response_payload, cleanup_idempotency_ttl)
        cache.set(cooldown_key, {"ts": now_ts}, cleanup_cooldown_seconds)
        return jsonify(response_payload)

    @app.post("/api/finance/maintenance/cleanup-stale")
    @limiter.limit("2/day")
    @require_finance_key
    def finance_cleanup_stale_data():
        confirm_token = str(request.headers.get("X-Cleanup-Confirm", "")).strip()
        if confirm_token != cleanup_confirm_token:
            return jsonify({
                "error": "Confirmação obrigatória para limpeza.",
                "required_header": "X-Cleanup-Confirm",
                "required_value": cleanup_confirm_token,
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
        if confirm_token != cleanup_confirm_token:
            return jsonify({
                "error": "Confirmação obrigatória para migração.",
                "required_header": "X-Cleanup-Confirm",
                "required_value": cleanup_confirm_token,
            }), 400
        payload = repo.normalize_fin_asset_types()
        _invalidate_financial_state_cache(include_market=True)
        _audit("maintenance", "migrate_asset_types", None, payload)
        return jsonify({"ok": True, **payload})

    @app.get("/api/finance/maintenance/cleanup-duplicates")
    def finance_cleanup_duplicate_transactions_help():
        return jsonify({
            "ok": True,
            "status": "created",
            "message": "Use POST para executar a limpeza de duplicatas.",
            "method": "POST",
            "path": "/api/finance/maintenance/cleanup-duplicates",
            "required_headers": {
                "X-Cleanup-Confirm": cleanup_confirm_token,
                "X-Idempotency-Key": "<valor-unico>",
            },
            "cooldown_seconds": cleanup_cooldown_seconds,
        })