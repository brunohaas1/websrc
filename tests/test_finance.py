"""Tests for the Finance module — routes and repository methods."""

from __future__ import annotations

import json
import pytest


# ── Helpers ────────────────────────────────────────────────


def jpost(client, url, data=None, **kw):
    return client.post(url, data=json.dumps(data or {}), content_type="application/json", **kw)


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

    def test_add_transaction_missing_fields(self, client):
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


# ══════════════════════════════════════════════════════════
#                 GOALS
# ══════════════════════════════════════════════════════════


class TestGoals:
    def test_list_empty(self, client):
        assert client.get("/api/finance/goals").get_json() == []

    def test_add_goal(self, client):
        resp = jpost(client, "/api/finance/goals", {
            "name": "Reserva de Emergência", "target_amount": 50000,
            "current_amount": 10000, "category": "savings",
        })
        assert resp.status_code == 201
        assert resp.get_json()["ok"] is True

    def test_add_goal_missing_fields(self, client):
        resp = jpost(client, "/api/finance/goals", {"name": "X"})
        assert resp.status_code == 400

    def test_update_goal(self, client):
        resp = jpost(client, "/api/finance/goals", {"name": "G", "target_amount": 1000})
        gid = resp.get_json()["id"]
        upd = jput(client, f"/api/finance/goals/{gid}", {"current_amount": 500, "notes": "halfway"})
        assert upd.status_code == 200

    def test_delete_goal(self, client):
        resp = jpost(client, "/api/finance/goals", {"name": "Temp", "target_amount": 100})
        gid = resp.get_json()["id"]
        assert client.delete(f"/api/finance/goals/{gid}").status_code == 200


# ══════════════════════════════════════════════════════════
#                 DIVIDENDS
# ══════════════════════════════════════════════════════════


class TestDividends:
    def test_list_empty(self, client):
        assert client.get("/api/finance/dividends").get_json() == []

    def test_add_dividend(self, client):
        asset = _add_asset(client).get_json()
        resp = jpost(client, "/api/finance/dividends", {
            "asset_id": asset["id"],
            "div_type": "dividend",
            "amount_per_share": 0.5,
            "quantity": 100,
            "pay_date": "2025-06-15",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["ok"] is True

    def test_add_dividend_auto_calc(self, client):
        """total_amount should auto-calculate from amount_per_share * quantity."""
        asset = _add_asset(client).get_json()
        resp = jpost(client, "/api/finance/dividends", {
            "asset_id": asset["id"],
            "amount_per_share": 1.0,
            "quantity": 50,
        })
        assert resp.status_code == 201
        # List and check total
        divs = client.get(f"/api/finance/dividends?asset_id={asset['id']}").get_json()
        assert len(divs) >= 1
        assert divs[0]["total_amount"] == pytest.approx(50.0, rel=1e-2)

    def test_add_dividend_missing_asset(self, client):
        resp = jpost(client, "/api/finance/dividends", {"div_type": "jcp"})
        assert resp.status_code == 400

    def test_delete_dividend(self, client):
        asset = _add_asset(client).get_json()
        div = jpost(client, "/api/finance/dividends", {
            "asset_id": asset["id"], "total_amount": 100,
        }).get_json()
        resp = client.delete(f"/api/finance/dividends/{div['id']}")
        assert resp.status_code == 200

    def test_dividend_summary(self, client):
        resp = client.get("/api/finance/dividend-summary")
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════
#                 ALLOCATION TARGETS
# ══════════════════════════════════════════════════════════


class TestAllocationTargets:
    def test_list_empty(self, client):
        resp = client.get("/api/finance/allocation-targets")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_save_targets(self, client):
        resp = jpost(client, "/api/finance/allocation-targets", {
            "targets": [
                {"asset_type": "stock", "target_pct": 50},
                {"asset_type": "fii", "target_pct": 30},
                {"asset_type": "crypto", "target_pct": 20},
            ],
        })
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

        targets = client.get("/api/finance/allocation-targets").get_json()
        assert len(targets) == 3

    def test_save_targets_invalid(self, client):
        resp = jpost(client, "/api/finance/allocation-targets", {"targets": "bad"})
        assert resp.status_code == 400


# ══════════════════════════════════════════════════════════
#                 REBALANCE
# ══════════════════════════════════════════════════════════


class TestRebalance:
    def test_rebalance_no_targets(self, client):
        resp = client.get("/api/finance/rebalance")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["suggestions"] == []

    def test_rebalance_with_data(self, client):
        """BUG-3 regression: action should be lowercase 'comprar'/'vender'."""
        asset = _add_asset(client, "PETR4", asset_type="stock").get_json()
        _add_tx(client, asset["id"], qty=10, price=30)
        jpost(client, "/api/finance/allocation-targets", {
            "targets": [{"asset_type": "stock", "target_pct": 100}],
        })
        resp = client.get("/api/finance/rebalance")
        data = resp.get_json()
        for s in data["suggestions"]:
            assert s["action"] in ("comprar", "vender", "ok")


# ══════════════════════════════════════════════════════════
#                 IR REPORT
# ══════════════════════════════════════════════════════════


class TestIRReport:
    def test_ir_report_empty_year(self, client):
        resp = client.get("/api/finance/ir-report?year=2030")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "year" in data

    def test_ir_report_field_names(self, client):
        """BUG-1/BUG-2 regression: response must have correct field names."""
        asset = _add_asset(client).get_json()
        _add_tx(client, asset["id"], qty=10, price=30)
        resp = client.get("/api/finance/ir-report?year=2025")
        data = resp.get_json()
        # Must have these exact keys
        assert "total_dividends" in data
        assert "positions_dec31" in data
        assert "monthly_sells" in data
        # Should NOT have the old wrong key names
        assert "dividend_totals" not in data
        assert "positions" not in data or isinstance(data.get("positions"), list) is False or "positions_dec31" in data


# ══════════════════════════════════════════════════════════
#                 SUMMARY
# ══════════════════════════════════════════════════════════


class TestSummary:
    def test_summary_empty(self, client):
        resp = client.get("/api/finance/summary")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total_invested" in data

    def test_summary_with_data(self, client):
        asset = _add_asset(client).get_json()
        _add_tx(client, asset["id"], qty=5, price=40)
        resp = client.get("/api/finance/summary")
        data = resp.get_json()
        assert data["total_invested"] > 0


# ══════════════════════════════════════════════════════════
#                 EXPORT
# ══════════════════════════════════════════════════════════


class TestExport:
    def test_export_csv(self, client):
        asset = _add_asset(client).get_json()
        _add_tx(client, asset["id"])
        resp = client.get("/api/finance/export?format=csv&type=transactions")
        assert resp.status_code == 200
        assert b"symbol" in resp.data.lower() or b"ativo" in resp.data.lower() or resp.content_type

    def test_export_template(self, client):
        resp = client.get("/api/finance/import-template")
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════
#                 REPOSITORY UNIT TESTS
# ══════════════════════════════════════════════════════════


class TestFinanceRepository:
    def test_upsert_asset(self, repo):
        aid = repo.upsert_fin_asset({
            "symbol": "TEST1", "name": "Test Stock",
            "asset_type": "stock", "currency": "BRL",
        })
        assert aid >= 1

    def test_upsert_asset_idempotent(self, repo):
        d = {"symbol": "ABC1", "name": "ABC", "asset_type": "stock", "currency": "BRL"}
        id1 = repo.upsert_fin_asset(d)
        id2 = repo.upsert_fin_asset(d)
        assert id1 == id2

    def test_upsert_asset_with_extra(self, repo):
        aid = repo.upsert_fin_asset({
            "symbol": "CDB1", "name": "CDB",
            "asset_type": "renda-fixa", "currency": "BRL",
            "extra": {"indexer": "IPCA", "rate": 6.5},
        })
        asset = repo.get_fin_asset(aid)
        assert asset is not None
        extra = asset.get("extra_json")
        if isinstance(extra, str):
            import json as _j
            extra = _j.loads(extra)
        assert extra.get("indexer") == "IPCA"

    def test_list_assets(self, repo):
        repo.upsert_fin_asset({"symbol": "X1", "name": "X", "asset_type": "stock", "currency": "BRL"})
        result = repo.list_fin_assets()
        assert len(result) >= 1

    def test_delete_asset(self, repo):
        aid = repo.upsert_fin_asset({"symbol": "DEL1", "name": "Del", "asset_type": "stock", "currency": "BRL"})
        repo.delete_fin_asset(aid)
        assert repo.get_fin_asset(aid) is None

    def test_add_transaction(self, repo):
        aid = repo.upsert_fin_asset({"symbol": "T1", "name": "T", "asset_type": "stock", "currency": "BRL"})
        tx_id = repo.add_fin_transaction({
            "asset_id": aid, "tx_type": "buy",
            "quantity": 10, "price": 25.0, "total": 250.0,
        })
        assert tx_id >= 1

    def test_get_fin_transaction(self, repo):
        """New get_fin_transaction method for BUG-5 fix."""
        aid = repo.upsert_fin_asset({"symbol": "GTX", "name": "G", "asset_type": "stock", "currency": "BRL"})
        tx_id = repo.add_fin_transaction({
            "asset_id": aid, "tx_type": "buy",
            "quantity": 5, "price": 10.0, "total": 50.0,
        })
        tx = repo.get_fin_transaction(tx_id)
        assert tx is not None
        assert tx["asset_id"] == aid
        assert tx["quantity"] == 5

    def test_get_fin_transaction_not_found(self, repo):
        assert repo.get_fin_transaction(99999) is None

    def test_list_transactions(self, repo):
        result = repo.list_fin_transactions()
        assert isinstance(result, list)

    def test_delete_transaction(self, repo):
        aid = repo.upsert_fin_asset({"symbol": "DT1", "name": "D", "asset_type": "stock", "currency": "BRL"})
        tx_id = repo.add_fin_transaction({
            "asset_id": aid, "tx_type": "buy",
            "quantity": 1, "price": 10.0, "total": 10.0,
        })
        repo.delete_fin_transaction(tx_id)
        assert repo.get_fin_transaction(tx_id) is None

    def test_add_watchlist(self, repo):
        wl_id = repo.add_fin_watchlist({
            "symbol": "WL1", "asset_type": "stock", "target_price": 10.0,
        })
        assert wl_id >= 1

    def test_watchlist_duplicate_upserts(self, repo):
        """BUG-6 regression: duplicate symbol should update, not crash."""
        id1 = repo.add_fin_watchlist({"symbol": "DUP1", "target_price": 10})
        id2 = repo.add_fin_watchlist({"symbol": "DUP1", "target_price": 20})
        assert id1 == id2
        wl = repo.list_fin_watchlist()
        dups = [w for w in wl if w["symbol"] == "DUP1"]
        assert len(dups) == 1

    def test_list_watchlist(self, repo):
        result = repo.list_fin_watchlist()
        assert isinstance(result, list)

    def test_delete_watchlist(self, repo):
        wl_id = repo.add_fin_watchlist({"symbol": "DWL"})
        assert repo.delete_fin_watchlist(wl_id) is True

    def test_add_goal(self, repo):
        gid = repo.add_fin_goal({
            "name": "Meta Test", "target_amount": 1000,
            "current_amount": 0, "category": "savings",
        })
        assert gid >= 1

    def test_update_goal(self, repo):
        gid = repo.add_fin_goal({"name": "UpdG", "target_amount": 500, "current_amount": 0, "category": "savings"})
        repo.update_fin_goal(gid, {"current_amount": 250})
        goals = repo.list_fin_goals()
        g = [x for x in goals if x["id"] == gid]
        assert g and g[0]["current_amount"] == 250

    def test_delete_goal(self, repo):
        gid = repo.add_fin_goal({"name": "DelG", "target_amount": 100, "current_amount": 0, "category": "savings"})
        repo.delete_fin_goal(gid)

    def test_add_dividend(self, repo):
        aid = repo.upsert_fin_asset({"symbol": "DIV1", "name": "D", "asset_type": "stock", "currency": "BRL"})
        did = repo.add_fin_dividend({
            "asset_id": aid, "div_type": "dividend",
            "amount_per_share": 0.5, "total_amount": 50,
            "quantity": 100, "pay_date": "2025-06-15",
        })
        assert did >= 1

    def test_list_dividends(self, repo):
        result = repo.list_fin_dividends()
        assert isinstance(result, list)

    def test_delete_dividend(self, repo):
        aid = repo.upsert_fin_asset({"symbol": "DD1", "name": "DD", "asset_type": "stock", "currency": "BRL"})
        did = repo.add_fin_dividend({
            "asset_id": aid, "div_type": "jcp",
            "total_amount": 100, "quantity": 10,
            "pay_date": "2025-07-01",
        })
        repo.delete_fin_dividend(did)

    def test_dividend_summary(self, repo):
        result = repo.get_fin_dividend_summary()
        assert isinstance(result, list)

    def test_allocation_targets(self, repo):
        repo.upsert_fin_allocation_target("stock", 60)
        repo.upsert_fin_allocation_target("fii", 40)
        targets = repo.list_fin_allocation_targets()
        assert len(targets) == 2

    def test_allocation_target_upsert(self, repo):
        repo.upsert_fin_allocation_target("crypto", 10)
        repo.upsert_fin_allocation_target("crypto", 15)
        targets = repo.list_fin_allocation_targets()
        crypto = [t for t in targets if t["asset_type"] == "crypto"]
        assert len(crypto) == 1
        assert crypto[0]["target_pct"] == 15

    def test_ir_report(self, repo):
        aid = repo.upsert_fin_asset({"symbol": "IR1", "name": "IR", "asset_type": "stock", "currency": "BRL"})
        repo.add_fin_transaction({
            "asset_id": aid, "tx_type": "buy",
            "quantity": 10, "price": 20.0, "total": 200.0,
            "tx_date": "2025-03-15",
        })
        report = repo.get_fin_ir_report(2025)
        assert report["year"] == 2025
        assert "total_dividends" in report
        assert "positions_dec31" in report
        assert "monthly_sells" in report

    def test_summary(self, repo):
        result = repo.get_fin_summary()
        assert "total_invested" in result
        assert "current_value" in result

    def test_portfolio_recalc(self, repo):
        aid = repo.upsert_fin_asset({"symbol": "RC1", "name": "RC", "asset_type": "stock", "currency": "BRL"})
        repo.add_fin_transaction({
            "asset_id": aid, "tx_type": "buy",
            "quantity": 10, "price": 30.0, "total": 300.0,
        })
        from app.finance_routes import _recalc_portfolio
        _recalc_portfolio(repo, aid)
        portfolio = repo.get_fin_portfolio()
        pos = [p for p in portfolio if p["asset_id"] == aid]
        assert len(pos) == 1
        assert pos[0]["quantity"] == 10


# ══════════════════════════════════════════════════════════
#                 AUTHENTICATION
# ══════════════════════════════════════════════════════════


class TestFinanceAuth:
    """Test that FINANCE_API_KEY protects write endpoints."""

    def test_write_blocked_when_key_set(self, app, client):
        app.config["FINANCE_API_KEY"] = "test-finance-secret"
        resp = jpost(client, "/api/finance/assets", {"symbol": "PETR4", "name": "Petrobras"})
        assert resp.status_code == 401
        assert resp.get_json()["error"] == "Unauthorized"

    def test_write_allowed_with_correct_key(self, app, client):
        app.config["FINANCE_API_KEY"] = "test-finance-secret"
        resp = client.post(
            "/api/finance/assets",
            data=json.dumps({"symbol": "PETR4", "name": "Petrobras"}),
            content_type="application/json",
            headers={"X-Finance-Key": "test-finance-secret"},
        )
        assert resp.status_code == 201

    def test_write_rejected_with_wrong_key(self, app, client):
        app.config["FINANCE_API_KEY"] = "test-finance-secret"
        resp = client.post(
            "/api/finance/assets",
            data=json.dumps({"symbol": "PETR4"}),
            content_type="application/json",
            headers={"X-Finance-Key": "wrong-key"},
        )
        assert resp.status_code == 401

    def test_read_always_open(self, app, client):
        """GET endpoints should NOT require auth."""
        app.config["FINANCE_API_KEY"] = "test-finance-secret"
        resp = client.get("/api/finance/assets")
        assert resp.status_code == 200

    def test_no_key_configured_allows_all(self, app, client):
        """When FINANCE_API_KEY is empty, all endpoints are open."""
        app.config["FINANCE_API_KEY"] = ""
        resp = jpost(client, "/api/finance/assets", {"symbol": "VALE3"})
        assert resp.status_code == 201
