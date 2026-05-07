"""Finance performance and market history routes."""

from __future__ import annotations

import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests as http_requests
from flask import jsonify, request


def register_performance_routes(
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
    _track_api_provider_usage = helpers.get("_track_api_provider_usage", lambda *args, **kwargs: None)
    _track_api_provider_latency = helpers.get("_track_api_provider_latency", lambda *args, **kwargs: None)

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
                    "captured_at": row["captured_at"],
                    "price": row["price"],
                    "normalized_pct": round(((row["price"] / base) - 1.0) * 100.0, 4),
                }
                for row in rows
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
        for tx in txs:
            date_key = str(tx.get("tx_date") or "")[:10]
            if not date_key:
                continue
            signal = -1.0 if str(tx.get("tx_type") or "buy").lower() == "buy" else 1.0
            cashflows[date_key] = float(cashflows.get(date_key, 0.0)) + signal * float(tx.get("total") or 0)
        today_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cashflows[today_key] = float(cashflows.get(today_key, 0.0)) + float(current_value)

        flows = [(key, value) for key, value in sorted(cashflows.items()) if abs(value) > 1e-9]
        irr = None
        if len(flows) >= 2:
            base = datetime.strptime(flows[0][0], "%Y-%m-%d")
            timed = [((datetime.strptime(d, "%Y-%m-%d") - base).days / 365.0, value) for d, value in flows]
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
