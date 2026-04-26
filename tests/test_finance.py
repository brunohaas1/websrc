"""Tests for the Finance module — routes and repository methods."""

from __future__ import annotations

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



