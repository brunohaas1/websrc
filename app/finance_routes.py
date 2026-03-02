"""Financial dashboard routes."""

import logging

import requests as http_requests
from flask import Flask, jsonify, render_template, request
from flask_limiter import Limiter

from .cache import get_cache
from .repository import Repository
from .security import sanitize_text


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

    # ── Assets CRUD ─────────────────────────────────────────

    @app.get("/api/finance/assets")
    @limiter.limit("30/minute")
    def finance_list_assets():
        return jsonify(repo.list_fin_assets())

    @app.post("/api/finance/assets")
    @limiter.limit("15/minute")
    def finance_add_asset():
        body = request.get_json(silent=True)
        if not body or not body.get("symbol"):
            return jsonify({"error": "symbol obrigatório"}), 400
        data = {
            "symbol": sanitize_text(str(body["symbol"]).upper().strip(), 20),
            "name": sanitize_text(str(body.get("name", body["symbol"])), 100),
            "asset_type": sanitize_text(
                str(body.get("asset_type", "stock")), 20,
            ),
            "currency": sanitize_text(str(body.get("currency", "BRL")), 10),
        }
        asset_id = repo.upsert_fin_asset(data)
        return jsonify({"ok": True, "id": asset_id}), 201

    @app.delete("/api/finance/assets/<int:asset_id>")
    @limiter.limit("15/minute")
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

        cache.delete("finance:summary")
        return jsonify({"ok": True, "id": tx_id}), 201

    @app.delete("/api/finance/transactions/<int:tx_id>")
    @limiter.limit("15/minute")
    def finance_delete_transaction(tx_id: int):
        # Get asset_id before deleting
        txns = repo.list_fin_transactions(limit=500)
        asset_id = None
        for t in txns:
            if t.get("id") == tx_id:
                asset_id = t.get("asset_id")
                break
        repo.delete_fin_transaction(tx_id)
        if asset_id:
            _recalc_portfolio(repo, asset_id)
        cache.delete("finance:summary")
        return jsonify({"ok": True})

    # ── Watchlist ───────────────────────────────────────────

    @app.get("/api/finance/watchlist")
    @limiter.limit("30/minute")
    def finance_list_watchlist():
        return jsonify(repo.list_fin_watchlist())

    @app.post("/api/finance/watchlist")
    @limiter.limit("15/minute")
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
        wl_id = repo.add_fin_watchlist(data)
        return jsonify({"ok": True, "id": wl_id}), 201

    @app.delete("/api/finance/watchlist/<int:wl_id>")
    @limiter.limit("15/minute")
    def finance_delete_watchlist(wl_id: int):
        repo.delete_fin_watchlist(wl_id)
        return jsonify({"ok": True})

    # ── Goals ───────────────────────────────────────────────

    @app.get("/api/finance/goals")
    @limiter.limit("30/minute")
    def finance_list_goals():
        return jsonify(repo.list_fin_goals())

    @app.post("/api/finance/goals")
    @limiter.limit("15/minute")
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
    def finance_delete_goal(goal_id: int):
        repo.delete_fin_goal(goal_id)
        return jsonify({"ok": True})

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

        # Fetch BR stock data from brapi.dev
        if stock_symbols:
            try:
                syms = ",".join(stock_symbols)
                resp = http_requests.get(
                    f"https://brapi.dev/api/quote/{syms}",
                    params={"fundamental": "true"},
                    timeout=10,
                )
                if resp.ok:
                    data = resp.json()
                    for item in data.get("results", []):
                        sym = item.get("symbol", "")
                        results["stocks"][sym] = {
                            "symbol": sym,
                            "name": item.get("longName", sym),
                            "price": item.get("regularMarketPrice"),
                            "previous_close": item.get(
                                "regularMarketPreviousClose",
                            ),
                            "change": item.get("regularMarketChange"),
                            "change_pct": item.get(
                                "regularMarketChangePercent",
                            ),
                            "volume": item.get("regularMarketVolume"),
                            "market_cap": item.get("marketCap"),
                            "high": item.get("regularMarketDayHigh"),
                            "low": item.get("regularMarketDayLow"),
                            "updated": item.get("regularMarketTime"),
                        }
                        # Update asset in DB
                        repo.upsert_fin_asset({
                            "symbol": sym,
                            "name": item.get("longName", sym),
                            "asset_type": "stock",
                            "current_price": item.get(
                                "regularMarketPrice",
                            ),
                            "previous_close": item.get(
                                "regularMarketPreviousClose",
                            ),
                            "day_change": item.get("regularMarketChange"),
                            "day_change_pct": item.get(
                                "regularMarketChangePercent",
                            ),
                            "market_cap": item.get("marketCap"),
                            "volume": item.get("regularMarketVolume"),
                            "extra": {
                                "high": item.get("regularMarketDayHigh"),
                                "low": item.get("regularMarketDayLow"),
                            },
                        })
            except Exception as exc:
                logger.warning("brapi.dev fetch failed: %s", exc)

        # Fetch crypto from CoinGecko
        if crypto_ids:
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
                        repo.upsert_fin_asset({
                            "symbol": cid.upper(),
                            "name": cid.title(),
                            "asset_type": "crypto",
                            "currency": "BRL",
                            "current_price": info.get("brl"),
                            "day_change_pct": info.get("brl_24h_change"),
                            "market_cap": info.get("brl_market_cap"),
                            "volume": info.get("brl_24h_vol"),
                        })
            except Exception as exc:
                logger.warning("CoinGecko fetch failed: %s", exc)

        # Fetch market indices (IBOV, IFIX, etc)
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

        cache.set("finance:market", results, 120)
        return jsonify(results)

    # ── AI Financial Analysis ───────────────────────────────

    @app.post("/api/finance/ai-analysis")
    @limiter.limit("6/minute")
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
                    "max_tokens": 800,
                    "temperature": 0.7,
                },
                timeout=app.config.get("AI_LOCAL_TIMEOUT_SECONDS", 30),
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

    # ── AI Chat Financeiro ──────────────────────────────────

    @app.post("/api/finance/ai-chat")
    @limiter.limit("8/minute")
    def finance_ai_chat():
        """Open-ended financial chat with AI."""
        if not app.config.get("AI_LOCAL_ENABLED"):
            return jsonify({"error": "IA local não habilitada"}), 503

        body = request.get_json(silent=True) or {}
        user_msg = sanitize_text(str(body.get("message", "")), 800)
        if not user_msg:
            return jsonify({"error": "message obrigatório"}), 400

        summary = repo.get_fin_summary()
        currency = repo.list_currency_rates()

        ctx = (
            f"Portfólio: R${summary['current_value']:,.2f} "
            f"(P&L {summary['total_pnl_pct']:+.1f}%). "
        )
        for p in summary.get("portfolio", [])[:10]:
            ctx += f"{p['symbol']}:{p['quantity']:.0f}un "
        for c in currency:
            ctx += f"{c['pair']}:R${c['rate']:.2f} "

        system_prompt = (
            "Você é um assistente financeiro pessoal. Responda em português "
            "de forma clara e objetiva. Use markdown.\n"
            "Dados do usuário: " + ctx
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
                    "max_tokens": 500,
                    "temperature": 0.7,
                },
                timeout=app.config.get("AI_LOCAL_TIMEOUT_SECONDS", 30),
            )
            if resp.ok:
                data = resp.json()
                choices = data.get("choices", [])
                answer = (
                    choices[0]["message"]["content"]
                    if choices else "Sem resposta"
                )
                return jsonify({"answer": answer})
            return jsonify({
                "error": f"AI retornou {resp.status_code}",
            }), 502
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
