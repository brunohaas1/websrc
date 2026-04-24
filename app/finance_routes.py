"""Financial dashboard routes."""

import csv
import io
import json
import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests as http_requests
from flask import Flask, jsonify, render_template, request
from flask_limiter import Limiter

from .cache import get_cache
from .repository import Repository
from .security import require_finance_key, sanitize_text


def register_finance_routes(app: Flask, limiter: Limiter) -> None:
    logger = logging.getLogger(__name__)
    repo = Repository(app.config["DATABASE_TARGET"])
    cache = get_cache(app.config)

    # ── Page ────────────────────────────────────────────────

    @app.get("/finance")
    def finance_page():
        return render_template("finance.html")

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
        cache.set("finance:summary", summary, 60)
        return jsonify(summary)

    # ── Finance Settings (keys & providers) ───────────────

    FINANCE_SETTINGS_SCHEMA: dict[str, dict] = {
        "brapi_token": {
            "type": "str", "max_len": 300, "default": "", "secret": True,
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

    def _audit(action: str, target_type: str, target_id: int | None, payload: dict | None = None) -> None:
        try:
            repo.add_fin_audit_log(action, target_type, target_id, payload or {})
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
        cache.delete("finance:market")
        cache.delete("finance:summary")

        return jsonify({"updated": list(valid.keys()), "count": len(valid)})

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
        return jsonify({"ok": True, "id": asset_id}), 201

    @app.delete("/api/finance/assets/<int:asset_id>")
    @limiter.limit("15/minute")
    @require_finance_key
    def finance_delete_asset(asset_id: int):
        repo.delete_fin_asset(asset_id)
        return jsonify({"ok": True})

    @app.get("/api/finance/assets/<int:asset_id>/history")
    @limiter.limit("30/minute")
    def finance_asset_history(asset_id: int):
        limit = min(365, max(1, int(request.args.get("limit", "90"))))
        return jsonify(repo.get_fin_asset_history(asset_id, limit))

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
        data = {
            "asset_id": int(body["asset_id"]),
            "tx_type": tx_type,
            "quantity": qty,
            "price": price,
            "total": total,
            "fees": fees,
            "notes": sanitize_text(str(body.get("notes", "")), 500),
            "tx_date": str(body.get("tx_date", "")),
        }
        tx_id = repo.add_fin_transaction(data)

        # Update portfolio automatically
        _recalc_portfolio(repo, data["asset_id"])
        _audit("add", "transaction", tx_id, {"asset_id": data["asset_id"], "tx_type": tx_type})

        cache.delete("finance:summary")
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
        cache.delete("finance:summary")
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
        cache.delete("finance:summary")
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
                cache.delete("finance:summary")
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
        cache.delete("finance:summary")
        _audit("batch_update", "transaction", None, {"count": updated, "tx_ids": tx_ids, "fields": sorted(list(data.keys()))})
        return jsonify({"ok": True, "updated": updated})

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
        return jsonify({"ok": True})

    @app.delete("/api/finance/goals/<int:goal_id>")
    @limiter.limit("15/minute")
    @require_finance_key
    def finance_delete_goal(goal_id: int):
        repo.delete_fin_goal(goal_id)
        return jsonify({"ok": True})

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

        cache.delete("finance:summary")
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

        cache.delete("finance:summary")
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

        cache.delete("finance:summary")
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
        if data["amount_per_share"] > 0 and data["quantity"] > 0 and not data["total_amount"]:
            data["total_amount"] = data["amount_per_share"] * data["quantity"]
        div_id = repo.add_fin_dividend(data)
        cache.delete("finance:summary")
        return jsonify({"ok": True, "id": div_id}), 201

    @app.delete("/api/finance/dividends/<int:div_id>")
    @limiter.limit("15/minute")
    @require_finance_key
    def finance_delete_dividend(div_id: int):
        repo.delete_fin_dividend(div_id)
        cache.delete("finance:summary")
        return jsonify({"ok": True})

    @app.get("/api/finance/dividend-summary")
    @limiter.limit("30/minute")
    def finance_dividend_summary():
        return jsonify(repo.get_fin_dividend_summary())

    # ── Asset Price History ─────────────────────────────────

    @app.get("/api/finance/asset-history/<int:asset_id>")
    @limiter.limit("30/minute")
    def finance_asset_history_alt(asset_id: int):
        limit = min(365, max(1, int(request.args.get("limit", "90"))))
        return jsonify(repo.get_fin_asset_history(asset_id, limit))

    @app.get("/api/finance/portfolio-history")
    @limiter.limit("30/minute")
    def finance_portfolio_history():
        limit = min(365, max(1, int(request.args.get("limit", "90"))))
        return jsonify(repo.get_fin_total_history(limit))

    @app.get("/api/finance/benchmark-history")
    @limiter.limit("20/minute")
    def finance_benchmark_history():
        benchmark = str(request.args.get("benchmark", "ibov")).strip().lower()
        limit = min(365, max(1, int(request.args.get("limit", "180"))))

        benchmark_map = {
            "ibov": "%5EBVSP",
        }
        if benchmark not in benchmark_map:
            return jsonify({"error": "benchmark inválido"}), 400

        cache_key = f"finance:benchmark:{benchmark}:{limit}"
        cached = cache.get(cache_key)
        if cached:
            return jsonify(cached)

        if limit <= 30:
            rng = "1mo"
        elif limit <= 90:
            rng = "3mo"
        elif limit <= 180:
            rng = "6mo"
        else:
            rng = "1y"

        try:
            resp = http_requests.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{benchmark_map[benchmark]}",
                params={"interval": "1d", "range": rng},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            if not resp.ok:
                return jsonify([])

            payload = resp.json()
            result = ((payload.get("chart") or {}).get("result") or [None])[0] or {}
            timestamps = result.get("timestamp") or []
            closes = (((result.get("indicators") or {}).get("quote") or [{}])[0]).get("close") or []

            rows: list[dict] = []
            for ts, close in zip(timestamps, closes):
                if close is None:
                    continue
                dt = datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d")
                rows.append({"captured_at": dt, "price": float(close)})

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
            cache.set(cache_key, normalized, 600)
            return jsonify(normalized)
        except Exception as exc:
            logger.warning("benchmark history fetch failed (%s): %s", benchmark, exc)
            return jsonify([])

    @app.get("/api/finance/invested-history")
    @limiter.limit("30/minute")
    def finance_invested_history():
        limit = min(365, max(1, int(request.args.get("limit", "180"))))
        asset_id = request.args.get("asset_id", type=int)

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

        return jsonify(rows[-limit:])

    @app.get("/api/finance/metrics/performance")
    @limiter.limit("20/minute")
    def finance_performance_metrics():
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

        return jsonify(
            {
                "current_value": round(float(current_value), 2),
                "invested": round(float(invested), 2),
                "simple_return_pct": round(float(simple_return), 2),
                "irr_pct": round(float(irr), 2) if irr is not None else None,
                "cashflow_points": len(flows),
            }
        )

    @app.get("/api/finance/audit")
    @limiter.limit("20/minute")
    @require_finance_key
    def finance_audit_logs():
        limit = min(300, max(1, int(request.args.get("limit", "100"))))
        return jsonify(repo.list_fin_audit_logs(limit))

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
        return jsonify(repo.list_fin_allocation_targets())

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

        results: dict = {"stocks": {}, "crypto": {}, "indices": {}}

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

                # 1) brapi: one asset per request
                try:
                    params = {"fundamental": "true"}
                    if brapi_token:
                        params["token"] = brapi_token
                    resp = http_requests.get(
                        f"https://brapi.dev/api/quote/{sym}",
                        params=params,
                        timeout=10,
                    )
                    if resp.ok:
                        data = resp.json()
                        items = data.get("results", [])
                        if items:
                            item = items[0]
                            price = item.get("regularMarketPrice")
                            if price is not None:
                                _save_stock_quote(
                                    sym=sym,
                                    name=item.get("longName", sym),
                                    price=price,
                                    previous_close=item.get(
                                        "regularMarketPreviousClose",
                                    ),
                                    change=item.get("regularMarketChange"),
                                    change_pct=item.get(
                                        "regularMarketChangePercent",
                                    ),
                                    volume=item.get("regularMarketVolume"),
                                    market_cap=item.get("marketCap"),
                                    high=item.get("regularMarketDayHigh"),
                                    low=item.get("regularMarketDayLow"),
                                    updated=item.get("regularMarketTime"),
                                )
                                loaded = True
                except Exception as exc:
                    logger.warning("brapi.dev fetch failed for %s: %s", sym, exc)

                if loaded:
                    continue

                # 2) Yahoo fallback: one asset per request
                try:
                    yresp = http_requests.get(
                        "https://query1.finance.yahoo.com/v7/finance/quote",
                        params={"symbols": f"{sym}.SA"},
                        timeout=10,
                    )
                    if not yresp.ok:
                        continue
                    ydata = yresp.json()
                    items = ydata.get("quoteResponse", {}).get("result", [])
                    if not items:
                        continue
                    item = items[0]
                    price = item.get("regularMarketPrice")
                    if price is None:
                        continue
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
                    )
                except Exception as exc:
                    logger.warning("Yahoo Finance fetch failed for %s: %s", sym, exc)

        def _fetch_crypto():
            """Fetch crypto from CoinGecko."""
            if not crypto_ids:
                return
            try:
                ids_param = ",".join(crypto_ids)
                resp = http_requests.get(
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
                logger.warning("CoinGecko fetch failed: %s", exc)

        def _fetch_indices():
            """Fetch market indices (IBOV, etc)."""
            try:
                resp = http_requests.get(
                    "https://brapi.dev/api/quote/%5EBVSP",
                    timeout=8,
                )
                if resp.ok:
                    data = resp.json()
                    for item in data.get("results", []):
                        results["indices"][item.get("symbol", "IBOV")] = {
                            "name": item.get("longName", "Ibovespa"),
                            "price": item.get("regularMarketPrice"),
                            "change": item.get("regularMarketChange"),
                            "change_pct": item.get(
                                "regularMarketChangePercent",
                            ),
                        }
            except Exception as exc:
                logger.warning("indices fetch failed: %s", exc)

        # Run all fetches in parallel
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(_fetch_stocks),
                executor.submit(_fetch_crypto),
                executor.submit(_fetch_indices),
            ]
            for f in as_completed(futures):
                f.result()  # propagate any unexpected errors

        cache.set("finance:market", results, 120)
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
            cache.delete("finance:summary")
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
