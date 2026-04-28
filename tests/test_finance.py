"""Tests for the Finance module — routes and repository methods."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import pytest


# ── Helpers ────────────────────────────────────────────────


def jpost(client, url, data=None, **kw):
    return client.post(url, data=json.dumps(data or {}), content_type="application/json", **kw)


def cleanup_headers(key: str = "test-cleanup-1"):
    return {
        "X-Cleanup-Confirm": "CONFIRM_CLEANUP_DUPLICATES",
        "X-Idempotency-Key": key,
    }


def jput(client, url, data=None, **kw):
    return client.put(url, data=json.dumps(data or {}), content_type="application/json", **kw)


def _add_asset(client, symbol="PETR4", name="Petrobras PN", asset_type="stock"):
    return jpost(client, "/api/finance/assets", {"symbol": symbol, "name": name, "asset_type": asset_type})


def _add_tx(client, asset_id, qty=10, price=30.0, tx_type="buy"):
    return jpost(client, "/api/finance/transactions", {
        "asset_id": asset_id, "quantity": qty, "price": price,
        "tx_type": tx_type, "tx_date": "2025-01-15",
    })


# ══════════════════════════════════════════════════════════
#                 FINANCE PAGE
# ══════════════════════════════════════════════════════════


class TestFinancePage:
    def test_finance_page_renders(self, client):
        resp = client.get("/finance")
        assert resp.status_code == 200
        assert b"finance" in resp.data.lower()


# ══════════════════════════════════════════════════════════
#                 ASSETS
# ══════════════════════════════════════════════════════════


class TestAssets:
    def test_list_empty(self, client):
        resp = client.get("/api/finance/assets")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_add_asset(self, client):
        resp = _add_asset(client)
        data = resp.get_json()
        assert resp.status_code == 201
        assert data["ok"] is True
        assert data["id"] >= 1

    def test_add_asset_missing_symbol(self, client):
        resp = jpost(client, "/api/finance/assets", {"name": "Test"})
        assert resp.status_code == 400

    def test_add_asset_with_extra(self, client):
        """BUG-4 regression: extra field should be passed through."""
        resp = jpost(client, "/api/finance/assets", {
            "symbol": "CDB001", "name": "CDB Banco X",
            "asset_type": "renda-fixa",
            "extra": {"indexer": "CDI", "rate": 110, "maturity": "2026-06-01"},
        })
        assert resp.status_code == 201
        asset_id = resp.get_json()["id"]
        # Verify it was stored
        assets = client.get("/api/finance/assets").get_json()
        found = [a for a in assets if a["id"] == asset_id]
        assert found
        extra = found[0].get("extra_json")
        if isinstance(extra, str):
            extra = json.loads(extra)
        assert extra.get("indexer") == "CDI"

    def test_upsert_same_symbol(self, client):
        _add_asset(client, "VALE3", "Vale SA")
        resp2 = _add_asset(client, "VALE3", "Vale S.A. Updated")
        assert resp2.status_code == 201
        # Same ID should be returned
        assets = client.get("/api/finance/assets").get_json()
        vale = [a for a in assets if a["symbol"] == "VALE3"]
        assert len(vale) == 1

    def test_delete_asset(self, client):
        resp = _add_asset(client)
        asset_id = resp.get_json()["id"]
        del_resp = client.delete(f"/api/finance/assets/{asset_id}")
        assert del_resp.status_code == 200
        assert del_resp.get_json()["ok"] is True

    def test_asset_history_empty(self, client):
        resp = _add_asset(client)
        aid = resp.get_json()["id"]
        hist = client.get(f"/api/finance/assets/{aid}/history")
        assert hist.status_code == 200
        assert isinstance(hist.get_json(), list)

    def test_portfolio_history_empty(self, client):
        resp = client.get("/api/finance/portfolio-history")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_benchmark_history_invalid_benchmark(self, client):
        resp = client.get("/api/finance/benchmark-history?benchmark=foo")
        assert resp.status_code == 400

    def test_benchmark_history_supports_cdi_and_ipca(self, client):
        cdi = client.get("/api/finance/benchmark-history?benchmark=cdi&limit=30")
        ipca = client.get("/api/finance/benchmark-history?benchmark=ipca&limit=30")
        assert cdi.status_code == 200
        assert ipca.status_code == 200
        assert isinstance(cdi.get_json(), list)
        assert isinstance(ipca.get_json(), list)

    def test_invested_history_empty(self, client):
        resp = client.get("/api/finance/invested-history")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_invested_history_with_transactions(self, client):
        asset = _add_asset(client).get_json()
        _add_tx(client, asset["id"], qty=2, price=10)
        _add_tx(client, asset["id"], qty=1, price=20)
        resp = client.get(f"/api/finance/invested-history?asset_id={asset['id']}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) >= 1
        assert data[-1]["price"] == pytest.approx(40.0, rel=1e-2)

    def test_asset_history_uses_historical_quantity(self, client, app):
        from app.db import get_connection

        asset = _add_asset(client).get_json()
        aid = asset["id"]

        jpost(client, "/api/finance/transactions", {
            "asset_id": aid,
            "quantity": 10,
            "price": 10,
            "tx_type": "buy",
            "tx_date": "2025-01-01",
        })
        jpost(client, "/api/finance/transactions", {
            "asset_id": aid,
            "quantity": 5,
            "price": 11,
            "tx_type": "sell",
            "tx_date": "2025-01-03",
        })

        with get_connection(app.config["DATABASE_TARGET"]) as conn:
            conn.execute(
                """
                INSERT INTO fin_asset_history (asset_id, price, captured_at)
                VALUES (?, ?, ?)
                """,
                (aid, 10.0, "2025-01-01 10:00:00"),
            )
            conn.execute(
                """
                INSERT INTO fin_asset_history (asset_id, price, captured_at)
                VALUES (?, ?, ?)
                """,
                (aid, 12.0, "2025-01-02 10:00:00"),
            )
            conn.execute(
                """
                INSERT INTO fin_asset_history (asset_id, price, captured_at)
                VALUES (?, ?, ?)
                """,
                (aid, 11.0, "2025-01-03 10:00:00"),
            )
            conn.commit()

        resp = client.get(f"/api/finance/asset-history/{aid}?limit=10")
        assert resp.status_code == 200
        data = list(reversed(resp.get_json()))
        by_day = {item["captured_at"][:10]: float(item["price"]) for item in data}

        assert by_day["2025-01-01"] == pytest.approx(100.0, rel=1e-6)
        assert by_day["2025-01-02"] == pytest.approx(120.0, rel=1e-6)
        assert by_day["2025-01-03"] == pytest.approx(55.0, rel=1e-6)

    def test_portfolio_history_uses_historical_quantity(self, client, app):
        from app.db import get_connection

        asset = _add_asset(client, symbol="VALE3", name="Vale SA").get_json()
        aid = asset["id"]

        jpost(client, "/api/finance/transactions", {
            "asset_id": aid,
            "quantity": 10,
            "price": 10,
            "tx_type": "buy",
            "tx_date": "2025-01-01",
        })
        jpost(client, "/api/finance/transactions", {
            "asset_id": aid,
            "quantity": 5,
            "price": 11,
            "tx_type": "sell",
            "tx_date": "2025-01-03",
        })

        with get_connection(app.config["DATABASE_TARGET"]) as conn:
            conn.execute(
                """
                INSERT INTO fin_asset_history (asset_id, price, captured_at)
                VALUES (?, ?, ?)
                """,
                (aid, 10.0, "2025-01-01 10:00:00"),
            )
            conn.execute(
                """
                INSERT INTO fin_asset_history (asset_id, price, captured_at)
                VALUES (?, ?, ?)
                """,
                (aid, 12.0, "2025-01-02 10:00:00"),
            )
            conn.execute(
                """
                INSERT INTO fin_asset_history (asset_id, price, captured_at)
                VALUES (?, ?, ?)
                """,
                (aid, 11.0, "2025-01-03 10:00:00"),
            )
            conn.commit()

        resp = client.get("/api/finance/portfolio-history?limit=10")
        assert resp.status_code == 200
        data = list(reversed(resp.get_json()))
        by_day = {item["captured_at"][:10]: float(item["price"]) for item in data}

        assert by_day["2025-01-01"] == pytest.approx(100.0, rel=1e-6)
        assert by_day["2025-01-02"] == pytest.approx(120.0, rel=1e-6)
        assert by_day["2025-01-03"] == pytest.approx(55.0, rel=1e-6)

    def test_asset_history_includes_tx_only_period_before_market_snapshots(self, client, app):
        from app.db import get_connection

        asset = _add_asset(client, symbol="ITSA4", name="Itausa").get_json()
        aid = asset["id"]

        jpost(client, "/api/finance/transactions", {
            "asset_id": aid,
            "quantity": 10,
            "price": 10,
            "tx_type": "buy",
            "tx_date": "2025-01-01",
        })

        with get_connection(app.config["DATABASE_TARGET"]) as conn:
            conn.execute(
                """
                INSERT INTO fin_asset_history (asset_id, price, captured_at)
                VALUES (?, ?, ?)
                """,
                (aid, 12.0, "2025-01-10 10:00:00"),
            )
            conn.commit()

        resp = client.get(f"/api/finance/asset-history/{aid}?limit=30")
        assert resp.status_code == 200
        data = list(reversed(resp.get_json()))
        by_day = {item["captured_at"][:10]: float(item["price"]) for item in data}

        assert by_day["2025-01-01"] == pytest.approx(100.0, rel=1e-6)
        assert by_day["2025-01-10"] == pytest.approx(120.0, rel=1e-6)

    def test_portfolio_history_includes_tx_only_period_before_market_snapshots(self, client, app):
        from app.db import get_connection

        asset = _add_asset(client, symbol="ABEV3", name="Ambev").get_json()
        aid = asset["id"]

        jpost(client, "/api/finance/transactions", {
            "asset_id": aid,
            "quantity": 20,
            "price": 10,
            "tx_type": "buy",
            "tx_date": "2025-02-01",
        })

        with get_connection(app.config["DATABASE_TARGET"]) as conn:
            conn.execute(
                """
                INSERT INTO fin_asset_history (asset_id, price, captured_at)
                VALUES (?, ?, ?)
                """,
                (aid, 11.0, "2025-02-20 10:00:00"),
            )
            conn.commit()

        resp = client.get("/api/finance/portfolio-history?limit=30")
        assert resp.status_code == 200
        data = list(reversed(resp.get_json()))
        by_day = {item["captured_at"][:10]: float(item["price"]) for item in data}

        assert by_day["2025-02-01"] == pytest.approx(200.0, rel=1e-6)
        assert by_day["2025-02-20"] == pytest.approx(220.0, rel=1e-6)


# ══════════════════════════════════════════════════════════
#                 PORTFOLIO
# ══════════════════════════════════════════════════════════


class TestPortfolio:
    def test_portfolio_empty(self, client):
        resp = client.get("/api/finance/portfolio")
        assert resp.status_code == 200
        assert isinstance(resp.get_json(), list)

    def test_portfolio_after_buy(self, client):
        asset = _add_asset(client).get_json()
        _add_tx(client, asset["id"], qty=10, price=30)
        portfolio = client.get("/api/finance/portfolio").get_json()
        assert len(portfolio) >= 1
        pos = [p for p in portfolio if p.get("asset_id") == asset["id"]]
        assert len(pos) == 1
        assert pos[0]["quantity"] == 10


# ══════════════════════════════════════════════════════════
#                 TRANSACTIONS
# ══════════════════════════════════════════════════════════


class TestTransactions:
    def test_list_empty(self, client):
        resp = client.get("/api/finance/transactions")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_add_buy_transaction(self, client):
        asset = _add_asset(client).get_json()
        resp = _add_tx(client, asset["id"])
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["ok"] is True
        assert data["id"] >= 1

    def test_add_duplicate_transaction_is_rejected(self, client):
        asset = _add_asset(client).get_json()
        first = _add_tx(client, asset["id"], qty=10, price=30)
        assert first.status_code == 201

        second = _add_tx(client, asset["id"], qty=10, price=30)
        assert second.status_code == 409
        assert "duplicada" in second.get_json()["error"].lower()

    def test_cleanup_duplicate_transactions_recalculates_portfolio(
        self,
        client,
        app,
    ):
        from app.db import get_connection

        asset = _add_asset(client).get_json()
        tx1 = _add_tx(client, asset["id"], qty=10, price=30).get_json()
        _add_tx(client, asset["id"], qty=5, price=40)

        # Simulate old duplicate row already present in database.
        with get_connection(app.config["DATABASE_TARGET"]) as conn:
            conn.execute(
                """
                INSERT INTO fin_transactions
                    (asset_id, tx_type, quantity, price, total, fees, notes, tx_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (asset["id"], "buy", 10, 30, 300, 0, "", "2025-01-15"),
            )
            conn.commit()

        # Force a portfolio recalc while duplicate still exists,
        # without changing dedupe key fields.
        recalc_resp = jput(
            client,
            f"/api/finance/transactions/{tx1['id']}",
            {"fees": 0},
        )
        assert recalc_resp.status_code == 200

        before = client.get("/api/finance/portfolio").get_json()
        before_pos = [p for p in before if p.get("asset_id") == asset["id"]]
        assert before_pos[0]["quantity"] == pytest.approx(25.0)

        cleanup = jpost(
            client,
            "/api/finance/maintenance/cleanup-duplicates",
            {},
            headers=cleanup_headers("tx-cleanup-1"),
        )
        assert cleanup.status_code == 200
        payload = cleanup.get_json()
        assert payload["ok"] is True
        assert payload["transactions"]["deleted"] == 1
        assert payload["transactions"]["duplicates"] == 1

        txs_after = client.get("/api/finance/transactions").get_json()
        assert len([t for t in txs_after if t["asset_id"] == asset["id"]]) == 2

        after = client.get("/api/finance/portfolio").get_json()
        after_pos = [p for p in after if p.get("asset_id") == asset["id"]]
        assert after_pos[0]["quantity"] == pytest.approx(15.0)

    def test_cleanup_duplicates_get_returns_usage_help(self, client):
        resp = client.get("/api/finance/maintenance/cleanup-duplicates")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["method"] == "POST"

    def test_cleanup_duplicates_requires_confirmation_headers(self, client):
        resp = jpost(client, "/api/finance/maintenance/cleanup-duplicates", {})
        assert resp.status_code == 400
        data = resp.get_json()
        assert "X-Cleanup-Confirm" in data.get("required_header", "")

    def test_add_duplicate_dividend_is_rejected(self, client):
        asset = _add_asset(client).get_json()
        div_data = {
            "asset_id": asset["id"],
            "div_type": "dividend",
            "amount_per_share": 1.5,
            "total_amount": 15.0,
            "quantity": 10,
            "ex_date": "2025-03-01",
            "pay_date": "2025-03-15",
            "notes": "",
        }
        r1 = jpost(client, "/api/finance/dividends", div_data)
        assert r1.status_code == 201
        r2 = jpost(client, "/api/finance/dividends", div_data)
        assert r2.status_code == 409

    def test_cleanup_duplicate_dividends(self, client, app):
        asset = _add_asset(client).get_json()
        from app.db import get_connection
        with get_connection(app.config["DATABASE_TARGET"]) as conn:
            conn.execute(
                """INSERT INTO fin_dividends
                    (asset_id, div_type, amount_per_share, total_amount,
                     quantity, ex_date, pay_date, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (asset["id"], "dividend", 2.0, 20.0, 10, "2025-01-01", "2025-01-15", ""),
            )
            conn.execute(
                """INSERT INTO fin_dividends
                    (asset_id, div_type, amount_per_share, total_amount,
                     quantity, ex_date, pay_date, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (asset["id"], "dividend", 2.0, 20.0, 10, "2025-01-01", "2025-01-15", ""),
            )
            conn.commit()

        cleanup = jpost(
            client,
            "/api/finance/maintenance/cleanup-duplicates",
            {},
            headers=cleanup_headers("div-cleanup-1"),
        )
        assert cleanup.status_code == 200
        payload = cleanup.get_json()
        assert payload["ok"] is True
        assert payload["dividends"]["deleted"] == 1
        assert payload["dividends"]["duplicates"] == 1

    def test_cleanup_duplicates_idempotent_replay(self, client, app):
        asset = _add_asset(client).get_json()
        from app.db import get_connection

        with get_connection(app.config["DATABASE_TARGET"]) as conn:
            conn.execute(
                """INSERT INTO fin_dividends
                    (asset_id, div_type, amount_per_share, total_amount,
                     quantity, ex_date, pay_date, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (asset["id"], "dividend", 1.0, 10.0, 10, "2025-02-01", "2025-02-15", ""),
            )
            conn.execute(
                """INSERT INTO fin_dividends
                    (asset_id, div_type, amount_per_share, total_amount,
                     quantity, ex_date, pay_date, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (asset["id"], "dividend", 1.0, 10.0, 10, "2025-02-01", "2025-02-15", ""),
            )
            conn.commit()

        h = cleanup_headers("same-key-replay")
        first = jpost(client, "/api/finance/maintenance/cleanup-duplicates", {}, headers=h)
        assert first.status_code == 200
        first_payload = first.get_json()
        assert first_payload["dividends"]["deleted"] == 1

        second = jpost(client, "/api/finance/maintenance/cleanup-duplicates", {}, headers=h)
        assert second.status_code == 200
        second_payload = second.get_json()
        assert second_payload.get("idempotent_replay") is True


        resp = jpost(client, "/api/finance/transactions", {"asset_id": 1})
        assert resp.status_code == 400
        assert "Campos" in resp.get_json()["error"]

    def test_add_transaction_invalid_tx_type(self, client):
        asset = _add_asset(client).get_json()
        resp = jpost(client, "/api/finance/transactions", {
            "asset_id": asset["id"], "quantity": 10, "price": 10, "tx_type": "invalid",
        })
        assert resp.status_code == 400

    def test_delete_transaction(self, client):
        """BUG-5 regression: delete should not fetch all transactions."""
        asset = _add_asset(client).get_json()
        tx = _add_tx(client, asset["id"]).get_json()
        del_resp = client.delete(f"/api/finance/transactions/{tx['id']}")
        assert del_resp.status_code == 200
        assert del_resp.get_json()["ok"] is True

    def test_delete_recalcs_portfolio(self, client):
        asset = _add_asset(client).get_json()
        tx = _add_tx(client, asset["id"], qty=10, price=30).get_json()
        # Portfolio should show qty=10
        portfolio = client.get("/api/finance/portfolio").get_json()
        pos = [p for p in portfolio if p.get("asset_id") == asset["id"]]
        assert pos[0]["quantity"] == 10

        client.delete(f"/api/finance/transactions/{tx['id']}")
        # After delete, portfolio should be 0 or gone
        portfolio2 = client.get("/api/finance/portfolio").get_json()
        pos2 = [p for p in portfolio2 if p.get("asset_id") == asset["id"]]
        if pos2:
            assert pos2[0]["quantity"] == 0

    def test_list_filter_by_asset(self, client):
        a1 = _add_asset(client, "PETR4").get_json()
        a2 = _add_asset(client, "VALE3").get_json()
        _add_tx(client, a1["id"])
        _add_tx(client, a2["id"])
        resp = client.get(f"/api/finance/transactions?asset_id={a1['id']}")
        txs = resp.get_json()
        assert all(t["asset_id"] == a1["id"] for t in txs)

    def test_update_transaction(self, client):
        asset = _add_asset(client).get_json()
        tx = _add_tx(client, asset["id"], qty=10, price=30).get_json()
        resp = jput(client, f"/api/finance/transactions/{tx['id']}", {"quantity": 20, "price": 35})
        assert resp.status_code == 200
        txs = client.get("/api/finance/transactions").get_json()
        updated = [t for t in txs if t["id"] == tx["id"]]
        assert len(updated) == 1
        assert updated[0]["quantity"] == 20

    def test_update_transaction_invalid_type(self, client):
        asset = _add_asset(client).get_json()
        tx = _add_tx(client, asset["id"]).get_json()
        resp = jput(client, f"/api/finance/transactions/{tx['id']}", {"tx_type": "bad"})
        assert resp.status_code == 400

    def test_update_transaction_not_found(self, client):
        resp = jput(client, "/api/finance/transactions/99999", {"quantity": 5})
        assert resp.status_code == 404

    def test_batch_update_transactions(self, client):
        asset = _add_asset(client).get_json()
        tx1 = _add_tx(client, asset["id"], qty=2, price=10).get_json()
        tx2 = _add_tx(client, asset["id"], qty=3, price=12).get_json()
        resp = jput(
            client,
            "/api/finance/transactions/batch",
            {
                "tx_ids": [tx1["id"], tx2["id"]],
                "updates": {"fees": 1.25, "tx_type": "buy"},
            },
        )
        assert resp.status_code == 200
        assert resp.get_json()["updated"] == 2

        txs = client.get("/api/finance/transactions").get_json()
        changed = [t for t in txs if t["id"] in (tx1["id"], tx2["id"])]
        assert len(changed) == 2
        assert all(t["fees"] == pytest.approx(1.25) for t in changed)

    def test_batch_update_transactions_invalid_payload(self, client):
        resp = jput(client, "/api/finance/transactions/batch", {"tx_ids": [], "updates": {"fees": 1}})
        assert resp.status_code == 400



# ══════════════════════════════════════════════════════════
#                 WATCHLIST
# ══════════════════════════════════════════════════════════


class TestWatchlist:
    def test_list_empty(self, client):
        resp = client.get("/api/finance/watchlist")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_add_watchlist(self, client):
        resp = jpost(client, "/api/finance/watchlist", {
            "symbol": "BBDC4", "target_price": 15.5, "alert_above": True,
        })
        assert resp.status_code == 201
        assert resp.get_json()["ok"] is True

    def test_add_watchlist_missing_symbol(self, client):
        resp = jpost(client, "/api/finance/watchlist", {"target_price": 10})
        assert resp.status_code == 400

    def test_add_watchlist_duplicate_upserts(self, client):
        """BUG-6 regression: adding same symbol twice should NOT error 500."""
        jpost(client, "/api/finance/watchlist", {"symbol": "ITUB4", "target_price": 20})
        resp2 = jpost(client, "/api/finance/watchlist", {"symbol": "ITUB4", "target_price": 25})
        assert resp2.status_code == 201  # Should succeed, not 500

        wl = client.get("/api/finance/watchlist").get_json()
        itub = [w for w in wl if w["symbol"] == "ITUB4"]
        assert len(itub) == 1  # No duplicates

    def test_delete_watchlist(self, client):
        resp = jpost(client, "/api/finance/watchlist", {"symbol": "MGLU3"})
        wl_id = resp.get_json()["id"]
        del_resp = client.delete(f"/api/finance/watchlist/{wl_id}")
        assert del_resp.status_code == 200

    def test_update_watchlist(self, client):
        resp = jpost(client, "/api/finance/watchlist", {"symbol": "BBDC4", "target_price": 15.0})
        wl_id = resp.get_json()["id"]
        upd = jput(client, f"/api/finance/watchlist/{wl_id}", {"target_price": 20.0, "alert_above": True})
        assert upd.status_code == 200
        wl = client.get("/api/finance/watchlist").get_json()
        item = [w for w in wl if w["id"] == wl_id]
        assert len(item) == 1
        assert item[0]["target_price"] == pytest.approx(20.0)
        assert bool(item[0]["alert_above"]) is True

    def test_update_watchlist_not_found(self, client):
        resp = jput(client, "/api/finance/watchlist/99999", {"target_price": 10.0})
        assert resp.status_code == 404


class TestCashflow:
    def test_cashflow_list_empty(self, client):
        resp = client.get("/api/finance/cashflow")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_cashflow_create_and_filter_by_month(self, client):
        r1 = jpost(client, "/api/finance/cashflow", {
            "entry_type": "income",
            "amount": 5000,
            "category": "Salario",
            "description": "Pagamento mensal",
            "entry_date": "2026-04-10",
        })
        r2 = jpost(client, "/api/finance/cashflow", {
            "entry_type": "expense",
            "amount": 1200,
            "category": "Moradia",
            "description": "Aluguel",
            "entry_date": "2026-04-05",
        })
        assert r1.status_code == 201
        assert r2.status_code == 201

        april = client.get("/api/finance/cashflow?month=2026-04")
        assert april.status_code == 200
        payload = april.get_json()
        assert len(payload) == 2
        assert {p["entry_type"] for p in payload} == {"income", "expense"}

    def test_cashflow_summary(self, client):
        jpost(client, "/api/finance/cashflow", {
            "entry_type": "income",
            "amount": 1000,
            "category": "Freela",
            "description": "Projeto A",
            "entry_date": "2026-03-01",
        })
        jpost(client, "/api/finance/cashflow", {
            "entry_type": "expense",
            "amount": 400,
            "category": "Transporte",
            "description": "Combustivel",
            "entry_date": "2026-03-03",
        })

        resp = client.get("/api/finance/cashflow/summary?months=12")
        assert resp.status_code == 200
        summary = resp.get_json()
        assert summary["total_income"] >= 1000
        assert summary["total_expense"] >= 400
        assert "monthly" in summary
        assert isinstance(summary["monthly"], list)

    def test_cashflow_update_and_delete(self, client):
        create = jpost(client, "/api/finance/cashflow", {
            "entry_type": "expense",
            "amount": 200,
            "category": "Lazer",
            "description": "Cinema",
            "entry_date": "2026-04-20",
        })
        assert create.status_code == 201
        entry_id = create.get_json()["id"]

        upd = jput(client, f"/api/finance/cashflow/{entry_id}", {
            "amount": 250,
            "description": "Cinema + lanche",
        })
        assert upd.status_code == 200

        items = client.get("/api/finance/cashflow?month=2026-04").get_json()
        row = [i for i in items if i["id"] == entry_id][0]
        assert row["amount"] == pytest.approx(250)

        dele = client.delete(f"/api/finance/cashflow/{entry_id}")
        assert dele.status_code == 200

    def test_cashflow_validates_payload(self, client):
        bad_type = jpost(client, "/api/finance/cashflow", {
            "entry_type": "foo",
            "amount": 10,
            "description": "x",
            "entry_date": "2026-04-10",
        })
        assert bad_type.status_code == 400

        bad_amount = jpost(client, "/api/finance/cashflow", {
            "entry_type": "expense",
            "amount": -1,
            "description": "x",
            "entry_date": "2026-04-10",
        })
        assert bad_amount.status_code == 400

        bad_month_filter = client.get("/api/finance/cashflow?month=2026/04")
        assert bad_month_filter.status_code == 400

    def test_cashflow_analytics(self, client):
        jpost(client, "/api/finance/cashflow", {
            "entry_type": "income",
            "amount": 3000,
            "category": "Salario",
            "description": "Folha",
            "entry_date": "2026-04-05",
        })
        jpost(client, "/api/finance/cashflow", {
            "entry_type": "expense",
            "amount": 1000,
            "category": "Moradia",
            "description": "Aluguel",
            "entry_date": "2026-04-06",
        })

        resp = client.get("/api/finance/cashflow/analytics?month=2026-04")
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["month"] == "2026-04"
        assert payload["totals"]["income"] == pytest.approx(3000)
        assert payload["totals"]["expense"] == pytest.approx(1000)
        assert payload["totals"]["balance"] == pytest.approx(2000)
        assert isinstance(payload.get("top_expenses"), list)

    def test_cashflow_budget_roundtrip(self, client):
        put_resp = jput(client, "/api/finance/cashflow/budget", {
            "month": "2026-04",
            "budget": {
                "Moradia": 1500,
                "Alimentacao": 800,
            },
        })
        assert put_resp.status_code == 200
        put_data = put_resp.get_json()
        assert put_data["ok"] is True
        assert put_data["budget"]["Moradia"] == pytest.approx(1500)

        get_resp = client.get("/api/finance/cashflow/budget?month=2026-04")
        assert get_resp.status_code == 200
        get_data = get_resp.get_json()
        assert get_data["month"] == "2026-04"
        assert get_data["budget"]["Moradia"] == pytest.approx(1500)

    def test_cashflow_analytics_includes_budget_usage(self, client):
        jput(client, "/api/finance/cashflow/budget", {
            "month": "2026-04",
            "budget": {
                "Moradia": 1000,
            },
        })
        jpost(client, "/api/finance/cashflow", {
            "entry_type": "expense",
            "amount": 1200,
            "category": "Moradia",
            "description": "Aluguel",
            "entry_date": "2026-04-02",
        })

        resp = client.get("/api/finance/cashflow/analytics?month=2026-04")
        assert resp.status_code == 200
        payload = resp.get_json()
        items = payload.get("budget", {}).get("items", [])
        row = [i for i in items if i.get("category") == "Moradia"][0]
        assert row["spent"] == pytest.approx(1200)
        assert row["limit"] == pytest.approx(1000)
        assert bool(row["over_budget"]) is True

    def test_cashflow_rollover_copies_entries_and_skips_duplicates(self, client):
        jpost(client, "/api/finance/cashflow", {
            "entry_type": "expense",
            "amount": 300,
            "category": "Internet",
            "description": "Plano fibra",
            "entry_date": "2026-03-10",
        })
        jpost(client, "/api/finance/cashflow", {
            "entry_type": "income",
            "amount": 5000,
            "category": "Salario",
            "description": "Folha",
            "entry_date": "2026-03-05",
        })
        # Duplicate no mês destino para validar skip
        jpost(client, "/api/finance/cashflow", {
            "entry_type": "expense",
            "amount": 300,
            "category": "Internet",
            "description": "Plano fibra",
            "entry_date": "2026-04-10",
        })

        roll = jpost(client, "/api/finance/cashflow/rollover", {
            "source_month": "2026-03",
            "target_month": "2026-04",
            "entry_type": "all",
        })
        assert roll.status_code == 200
        data = roll.get_json()
        assert data["ok"] is True
        assert data["created"] == 1
        assert data["skipped"] == 1

        april = client.get("/api/finance/cashflow?month=2026-04").get_json()
        assert len(april) == 2
        assert len([r for r in april if r["entry_type"] == "income"]) == 1

    def test_cashflow_rollover_validates_payload(self, client):
        bad_same = jpost(client, "/api/finance/cashflow/rollover", {
            "source_month": "2026-04",
            "target_month": "2026-04",
            "entry_type": "all",
        })
        assert bad_same.status_code == 400

        bad_type = jpost(client, "/api/finance/cashflow/rollover", {
            "source_month": "2026-03",
            "target_month": "2026-04",
            "entry_type": "foo",
        })
        assert bad_type.status_code == 400

    def test_cashflow_reconciliation_status_flow(self, client):
        created = jpost(client, "/api/finance/cashflow", {
            "entry_type": "expense",
            "amount": 250,
            "category": "Internet",
            "description": "Plano",
            "entry_date": "2026-04-12",
        })
        assert created.status_code == 201
        entry_id = created.get_json()["id"]

        listed = client.get("/api/finance/cashflow?month=2026-04").get_json()
        row = [r for r in listed if r["id"] == entry_id][0]
        assert row["payment_status"] == "pending"

        status_resp = jput(client, f"/api/finance/cashflow/{entry_id}/status", {
            "status": "paid",
            "settled_at": "2026-04-13",
        })
        assert status_resp.status_code == 200
        status_data = status_resp.get_json()
        assert status_data["status"] == "paid"

        paid_only = client.get("/api/finance/cashflow?month=2026-04&status=paid")
        assert paid_only.status_code == 200
        paid_rows = paid_only.get_json()
        assert len([r for r in paid_rows if r["id"] == entry_id]) == 1

    def test_cashflow_reconciliation_rejects_invalid_status(self, client):
        created = jpost(client, "/api/finance/cashflow", {
            "entry_type": "expense",
            "amount": 100,
            "category": "Teste",
            "description": "Teste",
            "entry_date": "2026-04-01",
        })
        entry_id = created.get_json()["id"]

        bad = jput(client, f"/api/finance/cashflow/{entry_id}/status", {
            "status": "foo",
        })
        assert bad.status_code == 400

        bad_filter = client.get("/api/finance/cashflow?status=foo")
        assert bad_filter.status_code == 400

    def test_cashflow_due_alerts_for_pending_expenses(self, client):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        jpost(client, "/api/finance/cashflow", {
            "entry_type": "expense",
            "amount": 180,
            "category": "Energia",
            "description": "Conta de luz",
            "entry_date": today,
            "payment_status": "pending",
        })
        jpost(client, "/api/finance/cashflow", {
            "entry_type": "expense",
            "amount": 90,
            "category": "Internet",
            "description": "Conta paga",
            "entry_date": today,
            "payment_status": "paid",
            "settled_at": today,
        })

        resp = client.get("/api/finance/cashflow/alerts?days=7")
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["counts"]["total"] >= 1
        assert any(i.get("category") == "Energia" for i in payload["items"])
        assert not any(i.get("category") == "Internet" for i in payload["items"])

    def test_cashflow_advanced_filters_with_cost_center_subcategory_and_tags(self, client):
        jpost(client, "/api/finance/cashflow", {
            "entry_type": "expense",
            "amount": 450,
            "category": "Moradia",
            "subcategory": "Condominio",
            "cost_center": "Casa",
            "description": "Taxa mensal predio",
            "entry_date": "2026-04-08",
            "tags": ["fixo", "essencial"],
        })
        jpost(client, "/api/finance/cashflow", {
            "entry_type": "expense",
            "amount": 80,
            "category": "Lazer",
            "subcategory": "Cinema",
            "cost_center": "Pessoal",
            "description": "Filme",
            "entry_date": "2026-04-09",
            "tags": ["variavel"],
        })

        by_center = client.get("/api/finance/cashflow?cost_center=Casa")
        assert by_center.status_code == 200
        rows_center = by_center.get_json()
        assert len(rows_center) == 1
        assert rows_center[0]["subcategory"] == "Condominio"

        by_tag = client.get("/api/finance/cashflow?tag=essencial")
        assert by_tag.status_code == 200
        rows_tag = by_tag.get_json()
        assert len(rows_tag) == 1
        assert "essencial" in (rows_tag[0].get("tags") or [])

        by_q = client.get("/api/finance/cashflow?q=predio")
        assert by_q.status_code == 200
        rows_q = by_q.get_json()
        assert len(rows_q) == 1
        assert rows_q[0]["cost_center"] == "Casa"

    def test_cashflow_recurring_crud_and_run(self, client):
        create = jpost(client, "/api/finance/cashflow/recurring", {
            "entry_type": "expense",
            "amount": 120,
            "category": "Internet",
            "subcategory": "Fibra",
            "cost_center": "Casa",
            "description": "Assinatura internet",
            "frequency": "monthly",
            "day_of_month": 10,
            "start_date": "2026-01-01",
            "tags": ["fixo"],
        })
        assert create.status_code == 201
        recurring_id = create.get_json()["id"]

        listed = client.get("/api/finance/cashflow/recurring?active_only=1")
        assert listed.status_code == 200
        rows = listed.get_json()
        assert any(int(r.get("id") or 0) == recurring_id for r in rows)

        run = jpost(client, "/api/finance/cashflow/recurring/run", {
            "month": "2026-05",
        })
        assert run.status_code == 200
        run_data = run.get_json()
        assert run_data["ok"] is True
        assert run_data["created"] >= 1

        may = client.get("/api/finance/cashflow?month=2026-05&cost_center=Casa")
        assert may.status_code == 200
        may_rows = may.get_json()
        assert len(may_rows) >= 1
        assert any(r.get("description") == "Assinatura internet" for r in may_rows)

        upd = jput(client, f"/api/finance/cashflow/recurring/{recurring_id}", {
            "active": False,
        })
        assert upd.status_code == 200

        dele = client.delete(f"/api/finance/cashflow/recurring/{recurring_id}")
        assert dele.status_code == 200

    def test_audit_filters_by_target_type_and_action(self, client):
        created = jpost(client, "/api/finance/cashflow", {
            "entry_type": "expense",
            "amount": 90,
            "category": "Cafe",
            "description": "Padaria",
            "entry_date": "2026-04-14",
        })
        entry_id = created.get_json()["id"]

        jput(client, f"/api/finance/cashflow/{entry_id}/status", {
            "status": "paid",
            "settled_at": "2026-04-14",
        })

        resp = client.get(
            "/api/finance/audit?target_type=cashflow&action=status_update&limit=50",
        )
        assert resp.status_code == 200
        rows = resp.get_json()
        assert isinstance(rows, list)
        assert any(int(r.get("target_id") or 0) == entry_id for r in rows)

    def test_cashflow_audit_endpoint_filters_by_entry(self, client):
        created = jpost(client, "/api/finance/cashflow", {
            "entry_type": "expense",
            "amount": 50,
            "category": "TesteAudit",
            "description": "Item",
            "entry_date": "2026-04-14",
        })
        entry_id = created.get_json()["id"]

        jput(client, f"/api/finance/cashflow/{entry_id}", {
            "description": "Item editado",
        })

        resp = client.get(f"/api/finance/cashflow/audit?entry_id={entry_id}&limit=50")
        assert resp.status_code == 200
        rows = resp.get_json()
        assert isinstance(rows, list)
        assert len(rows) >= 2
        assert all(int(r.get("target_id") or 0) == entry_id for r in rows)


class TestFinanceSettings:
    def test_update_settings_and_read_back(self, client):
        resp = jput(client, "/api/finance/settings", {
            "brapi_monthly_limit": 20000,
            "brapi_reserve_pct": 10,
            "ai_local_enabled": False,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == 3

        settings = client.get("/api/finance/settings").get_json()
        assert str(settings["brapi_monthly_limit"]) == "20000"
        assert str(settings["brapi_reserve_pct"]) == "10"
        assert str(settings["ai_local_enabled"]) == "0"

    def test_update_settings_rejects_invalid_value(self, client):
        resp = jput(client, "/api/finance/settings", {
            "brapi_monthly_limit": "abc",
        })
        assert resp.status_code == 400


class TestGoals:
    def test_goal_create_update_delete(self, client):
        create = jpost(client, "/api/finance/goals", {
            "name": "Reserva de Emergencia",
            "target_amount": 30000,
            "current_amount": 1000,
            "category": "savings",
        })
        assert create.status_code == 201
        goal_id = create.get_json()["id"]

        upd = jput(client, f"/api/finance/goals/{goal_id}", {
            "current_amount": 2500,
            "notes": "Aporte mensal",
        })
        assert upd.status_code == 200

        goals = client.get("/api/finance/goals").get_json()
        row = [g for g in goals if g["id"] == goal_id][0]
        assert row["current_amount"] == pytest.approx(2500)

        dele = client.delete(f"/api/finance/goals/{goal_id}")
        assert dele.status_code == 200

    def test_goal_create_requires_required_fields(self, client):
        resp = jpost(client, "/api/finance/goals", {
            "name": "Sem alvo",
        })
        assert resp.status_code == 400


class TestPassiveIncomeGoal:
    def test_passive_income_goal_roundtrip(self, client):
        put_resp = jput(client, "/api/finance/goals/passive-income", {
            "target_monthly": 3500,
            "note": "Objetivo ate o fim do ano",
        })
        assert put_resp.status_code == 200
        put_data = put_resp.get_json()
        assert put_data["target_monthly"] == pytest.approx(3500)

        get_resp = client.get("/api/finance/goals/passive-income")
        assert get_resp.status_code == 200
        get_data = get_resp.get_json()
        assert get_data["target_monthly"] == pytest.approx(3500)

    def test_passive_income_goal_rejects_negative(self, client):
        resp = jput(client, "/api/finance/goals/passive-income", {
            "target_monthly": -10,
        })
        assert resp.status_code == 400


class TestCashflowNewFeatures:
    """Tests for budget alerts, KPIs, auto-classify, scenario, CSV/OFX import."""

    def test_budget_alerts_over_threshold(self, client):
        month = "2026-04"
        # set budget
        jput(client, "/api/finance/cashflow/budget", {
            "month": month,
            "budget": {"Alimentação": 500, "Lazer": 200},
        })
        # add expense over budget
        jpost(client, "/api/finance/cashflow", {
            "entry_type": "expense",
            "amount": 600,
            "category": "Alimentação",
            "entry_date": "2026-04-10",
        })
        resp = client.get(f"/api/finance/cashflow/budget/alerts?month={month}&threshold=80")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["month"] == month
        over = [a for a in data["alerts"] if a["category"] == "Alimentação"]
        assert over and over[0]["status"] == "over"

    def test_budget_alerts_returns_all_field(self, client):
        month = "2026-05"
        jput(client, "/api/finance/cashflow/budget", {
            "month": month,
            "budget": {"Transporte": 300},
        })
        resp = client.get(f"/api/finance/cashflow/budget/alerts?month={month}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "all" in data
        assert isinstance(data["all"], list)

    def test_kpis_endpoint_returns_expected_fields(self, client):
        month = "2026-04"
        jpost(client, "/api/finance/cashflow", {
            "entry_type": "income",
            "amount": 5000,
            "category": "Salário",
            "entry_date": "2026-04-01",
        })
        jpost(client, "/api/finance/cashflow", {
            "entry_type": "expense",
            "amount": 3000,
            "category": "Geral",
            "entry_date": "2026-04-05",
        })
        resp = client.get(f"/api/finance/cashflow/kpis?month={month}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "savings_rate_pct" in data
        assert "burn_rate" in data
        assert data["income"] == pytest.approx(5000)

    def test_auto_classify_updates_entries(self, client):
        month = "2026-04"
        # add classify rules
        jput(client, "/api/finance/cashflow/classify-rules", {
            "rules": [{"keyword": "mercado", "category": "Alimentação"}],
        })
        # add entry with empty category
        entry = jpost(client, "/api/finance/cashflow", {
            "entry_type": "expense",
            "amount": 75,
            "category": "",
            "description": "Compra mercado semanal",
            "entry_date": "2026-04-12",
        })
        entry_id = entry.get_json()["id"]
        # run auto-classify
        resp = client.post(
            "/api/finance/cashflow/auto-classify",
            json={"month": month},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["updated"] >= 1
        # check entry was classified
        entries = client.get(f"/api/finance/cashflow?month={month}").get_json()
        classified = [e for e in entries if e["id"] == entry_id]
        assert classified and classified[0]["category"] == "Alimentação"

    def test_classify_rules_roundtrip(self, client):
        resp = jput(client, "/api/finance/cashflow/classify-rules", {
            "rules": [
                {"keyword": "uber", "category": "Transporte"},
                {"keyword": "netflix", "category": "Entretenimento"},
            ],
        })
        assert resp.status_code == 200
        get_resp = client.get("/api/finance/cashflow/classify-rules")
        assert get_resp.status_code == 200
        rules = get_resp.get_json()["rules"]
        keywords = [r["keyword"] for r in rules]
        assert "uber" in keywords
        assert "netflix" in keywords

    def test_scenario_simulation(self, client):
        month = "2026-04"
        jpost(client, "/api/finance/cashflow", {
            "entry_type": "income", "amount": 5000, "category": "Salário",
            "entry_date": "2026-04-01",
        })
        jpost(client, "/api/finance/cashflow", {
            "entry_type": "expense", "amount": 1000, "category": "Restaurante",
            "entry_date": "2026-04-02",
        })
        resp = client.post("/api/finance/cashflow/scenario", json={
            "month": month,
            "adjustments": [{"category": "Restaurante", "reduction_pct": 50}],
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["impact"]["monthly_saving"] == pytest.approx(500)
        assert data["simulated"]["expense"] == pytest.approx(500)

    def test_scenario_bad_month(self, client):
        resp = client.post("/api/finance/cashflow/scenario", json={"month": "bad"})
        assert resp.status_code == 400

    def test_csv_import_basic(self, client):
        csv_content = (
            "date,amount,type,category,description\n"
            "2026-04-10,100.50,expense,Alimentação,Supermercado\n"
            "2026-04-11,200.00,income,Salário,Pagamento\n"
        )
        from io import BytesIO
        resp = client.post(
            "/api/finance/cashflow/import?month=2026-04",
            data={"file": (BytesIO(csv_content.encode()), "import.csv")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["imported"] == 2
        assert data["errors"] == []

    def test_csv_import_invalid_row_skipped(self, client):
        csv_content = (
            "date,amount,type,category,description\n"
            "not-a-date,100,expense,X,Y\n"
            "2026-04-12,50,expense,Z,W\n"
        )
        from io import BytesIO
        resp = client.post(
            "/api/finance/cashflow/import?month=2026-04",
            data={"file": (BytesIO(csv_content.encode()), "import.csv")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["imported"] == 1
        assert len(data["errors"]) == 1

    def test_import_unsupported_format(self, client):
        from io import BytesIO
        resp = client.post(
            "/api/finance/cashflow/import?month=2026-04",
            data={"file": (BytesIO(b"data"), "file.xls")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400

    def test_cashflow_attachments_lifecycle(self, client):
        from io import BytesIO

        created = jpost(client, "/api/finance/cashflow", {
            "entry_type": "expense",
            "amount": 80,
            "category": "Teste",
            "description": "Anexo",
            "entry_date": "2026-04-18",
        })
        assert created.status_code == 201
        entry_id = created.get_json()["id"]

        upload = client.post(
            f"/api/finance/cashflow/{entry_id}/attachments",
            data={"file": (BytesIO(b"comprovante-teste"), "comprovante.txt")},
            content_type="multipart/form-data",
        )
        assert upload.status_code == 201
        attachment_id = upload.get_json()["id"]

        listed = client.get(f"/api/finance/cashflow/{entry_id}/attachments")
        assert listed.status_code == 200
        rows = listed.get_json()
        assert len(rows) == 1
        assert rows[0]["id"] == attachment_id
        assert rows[0]["file_name"] == "comprovante.txt"

        downloaded = client.get(f"/api/finance/cashflow/attachments/{attachment_id}/download")
        assert downloaded.status_code == 200
        assert downloaded.data == b"comprovante-teste"
        assert downloaded.headers.get("Content-Type", "").startswith("text/plain")

        deleted = client.delete(f"/api/finance/cashflow/attachments/{attachment_id}")
        assert deleted.status_code == 200

        listed_after = client.get(f"/api/finance/cashflow/{entry_id}/attachments")
        assert listed_after.status_code == 200
        assert listed_after.get_json() == []

    def test_cashflow_closing_pdf_endpoint(self, client):
        jpost(client, "/api/finance/cashflow", {
            "entry_type": "income",
            "amount": 5000,
            "category": "Salario",
            "entry_date": "2026-04-01",
        })
        jpost(client, "/api/finance/cashflow", {
            "entry_type": "expense",
            "amount": 2100,
            "category": "Moradia",
            "entry_date": "2026-04-03",
        })

        resp = client.get("/api/finance/cashflow/closing-pdf?month=2026-04")
        assert resp.status_code == 200
        assert resp.data.startswith(b"%PDF")
        assert resp.headers.get("Content-Type", "").startswith("application/pdf")
        assert "fechamento-2026-04.pdf" in resp.headers.get("Content-Disposition", "")


class TestFinanceAdvanced:
    def test_performance_metrics(self, client):
        asset = _add_asset(client).get_json()
        _add_tx(client, asset["id"], qty=5, price=10)
        resp = client.get("/api/finance/metrics/performance")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "simple_return_pct" in data
        assert "current_value" in data

    def test_finance_audit_logs(self, client):
        _add_asset(client, symbol="BBAS3")
        resp = client.get("/api/finance/audit")
        assert resp.status_code == 200
        assert isinstance(resp.get_json(), list)


class TestFinanceObservability:
    def test_api_stats_includes_provider_metrics(self, client, app):
        from app.repository import Repository

        repo = Repository(app.config["DATABASE_TARGET"])
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        base = f"api_usage:{today}:market-data:yahoo"
        repo.set_setting(base, "10")
        repo.set_setting(f"{base}:ok", "8")
        repo.set_setting(f"{base}:err", "2")
        repo.set_setting(f"{base}:latency_sum_ms", "1200")
        repo.set_setting(f"{base}:latency_count", "10")

        resp = client.get("/api/finance/api-stats")
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["ok"] is True
        assert "provider_metrics" in payload
        yahoo = payload["provider_metrics"]["yahoo"]
        assert yahoo["total"] == 10
        assert yahoo["ok"] == 8
        assert yahoo["err"] == 2
        assert yahoo["success_rate"] == pytest.approx(0.8, rel=1e-6)
        assert yahoo["avg_latency_ms"] == pytest.approx(120.0, rel=1e-6)

    def test_finance_health_reports_degraded_quota(self, client, app):
        from app.repository import Repository

        repo = Repository(app.config["DATABASE_TARGET"])
        month_key = datetime.now(timezone.utc).strftime("%Y%m")
        repo.set_setting("brapi_monthly_limit", "100")
        repo.set_setting(f"brapi_usage:{month_key}", "100")

        resp = client.get("/api/finance/health")
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["ok"] is True
        assert payload["status"] == "degraded"
        quota = payload["checks"]["brapi_quota"]
        assert quota["status"] == "degraded"
        assert quota["remaining"] == 0



