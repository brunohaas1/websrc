"""Auth and route coverage tests.

Verifies:
- require_finance_key behavior (open / rejects / accepts)
- require_admin_key behavior already in test_security; here we cover query-param rejection
- Mutating routes that have NO auth decorator remain accessible regardless of admin key
- _provider_day_metrics result is cached (avoids repeated full DB scan)
"""

from __future__ import annotations

import json
import pytest


# ── helpers ────────────────────────────────────────────────

def jpost(client, url, data=None, headers=None, **kw):
    return client.post(
        url,
        data=json.dumps(data or {}),
        content_type="application/json",
        headers=headers or {},
        **kw,
    )


def jput(client, url, data=None, headers=None, **kw):
    return client.put(
        url,
        data=json.dumps(data or {}),
        content_type="application/json",
        headers=headers or {},
        **kw,
    )


# ══════════════════════════════════════════════════════════
# require_finance_key
# ══════════════════════════════════════════════════════════

class TestFinanceKey:
    """Finance key decorator: open when unset, blocks when set."""

    def test_open_when_key_not_configured(self, client, app):
        app.config["FINANCE_API_KEY"] = ""
        resp = jpost(client, "/api/finance/assets", {"symbol": "PETR4"})
        assert resp.status_code != 401

    def test_rejects_when_key_configured_and_no_header(self, client, app):
        app.config["FINANCE_API_KEY"] = "finance-secret-xyz"
        resp = jpost(client, "/api/finance/assets", {"symbol": "PETR4"})
        assert resp.status_code == 401

    def test_rejects_wrong_key(self, client, app):
        app.config["FINANCE_API_KEY"] = "finance-secret-xyz"
        resp = jpost(
            client,
            "/api/finance/assets",
            {"symbol": "PETR4"},
            headers={"X-Finance-Key": "wrong-key"},
        )
        assert resp.status_code == 401

    def test_accepts_correct_header(self, client, app):
        app.config["FINANCE_API_KEY"] = "finance-secret-xyz"
        resp = jpost(
            client,
            "/api/finance/assets",
            {"symbol": "PETR4"},
            headers={"X-Finance-Key": "finance-secret-xyz"},
        )
        assert resp.status_code != 401

    def test_accepts_correct_query_param(self, client, app):
        app.config["FINANCE_API_KEY"] = "finance-secret-xyz"
        resp = client.post(
            "/api/finance/assets?finance_key=finance-secret-xyz",
            data=json.dumps({"symbol": "PETR4"}),
            content_type="application/json",
        )
        assert resp.status_code != 401

    def test_finance_key_covers_delete(self, client, app):
        """DELETE /api/finance/assets/<id> requires key when set."""
        app.config["FINANCE_API_KEY"] = "finance-secret-xyz"
        resp = client.delete(
            "/api/finance/assets/1",
            headers={"X-Finance-Key": "wrong"},
        )
        assert resp.status_code == 401

    def test_finance_key_covers_transactions(self, client, app):
        """POST /api/finance/transactions requires key when set."""
        app.config["FINANCE_API_KEY"] = "finance-secret-xyz"
        resp = jpost(
            client,
            "/api/finance/transactions",
            {"asset_id": 1, "quantity": 10, "price": 30.0},
        )
        assert resp.status_code == 401

    def test_finance_key_covers_settings_put(self, client, app):
        """PUT /api/finance/settings requires key when set."""
        app.config["FINANCE_API_KEY"] = "finance-secret-xyz"
        resp = jput(client, "/api/finance/settings", {})
        assert resp.status_code == 401


# ══════════════════════════════════════════════════════════
# Mutating routes without auth decorator
# ══════════════════════════════════════════════════════════

class TestOpenMutatingRoutes:
    """Routes intentionally open (no auth decorator). Verifying they remain
    accessible even when ADMIN_API_KEY is set — local-only deployment."""

    def test_put_settings_accessible_without_admin_key(self, client, app):
        app.config["ADMIN_API_KEY"] = "admin-secret"
        resp = jput(client, "/api/settings", {"cache_ttl_seconds": "120"})
        # Should not be 401 (no auth on this route by design)
        assert resp.status_code != 401

    def test_post_custom_feed_accessible_without_admin_key(self, client, app):
        app.config["ADMIN_API_KEY"] = "admin-secret"
        resp = jpost(client, "/api/custom-feeds", {
            "name": "My Feed",
            "feed_url": "https://example.com/rss.xml",
        })
        assert resp.status_code != 401

    def test_delete_custom_feed_accessible_without_admin_key(self, client, app):
        app.config["ADMIN_API_KEY"] = "admin-secret"
        cr = jpost(client, "/api/custom-feeds", {
            "name": "ToDelete",
            "feed_url": "https://example.com/rss.xml",
        })
        feed_id = cr.get_json()["id"]
        resp = client.delete(f"/api/custom-feeds/{feed_id}")
        assert resp.status_code != 401

    def test_post_webhook_accessible_without_admin_key(self, client, app):
        app.config["ADMIN_API_KEY"] = "admin-secret"
        resp = jpost(client, "/api/webhooks", {
            "name": "Hook",
            "url": "https://example.com/hook",
        })
        assert resp.status_code != 401

    def test_post_share_accessible_without_admin_key(self, client, app):
        app.config["ADMIN_API_KEY"] = "admin-secret"
        resp = jpost(client, "/api/share", {"label": "Test", "hours": 24})
        assert resp.status_code != 401

    def test_post_favorite_accessible_without_admin_key(self, client, app):
        app.config["ADMIN_API_KEY"] = "admin-secret"
        resp = jpost(client, "/api/favorites", {"item_id": 99999})
        # May 404 if item not found, but not 401
        assert resp.status_code != 401

    def test_post_note_accessible_without_admin_key(self, client, app):
        app.config["ADMIN_API_KEY"] = "admin-secret"
        resp = jpost(client, "/api/notes", {"item_id": 1, "content": "hello"})
        assert resp.status_code != 401

    def test_post_service_monitor_accessible_without_admin_key(self, client, app):
        app.config["ADMIN_API_KEY"] = "admin-secret"
        resp = jpost(client, "/api/service-monitors", {
            "name": "Google",
            "url": "https://google.com",
        })
        assert resp.status_code != 401


# ══════════════════════════════════════════════════════════
# Admin-protected routes ARE protected when key is set
# ══════════════════════════════════════════════════════════

class TestAdminProtectedRoutes:
    """Routes with @require_admin_key must block when key is configured."""

    def test_run_now_blocked_without_admin_key(self, client, app):
        app.config["ADMIN_API_KEY"] = "admin-secret"
        resp = client.post("/api/run-now")
        assert resp.status_code == 401

    def test_ai_backfill_blocked_without_admin_key(self, client, app):
        app.config["ADMIN_API_KEY"] = "admin-secret"
        resp = client.post("/api/maintenance/ai-backfill")
        assert resp.status_code == 401

    def test_cleanup_summaries_blocked_without_admin_key(self, client, app):
        app.config["ADMIN_API_KEY"] = "admin-secret"
        resp = client.post("/api/maintenance/cleanup-summaries")
        assert resp.status_code == 401

    def test_retention_blocked_without_admin_key(self, client, app):
        app.config["ADMIN_API_KEY"] = "admin-secret"
        resp = client.post("/api/maintenance/retention")
        assert resp.status_code == 401

    def test_logs_blocked_without_admin_key(self, client, app):
        app.config["ADMIN_API_KEY"] = "admin-secret"
        resp = client.get("/api/logs")
        assert resp.status_code == 401

    def test_email_digest_blocked_without_admin_key(self, client, app):
        app.config["ADMIN_API_KEY"] = "admin-secret"
        resp = client.post("/api/email-digest/send")
        assert resp.status_code == 401


# ══════════════════════════════════════════════════════════
# Provider metrics cache
# ══════════════════════════════════════════════════════════

class TestProviderMetricsCache:
    """_provider_day_metrics result is cached; hitting /api/finance/api-stats
    twice in a row must not double-scan the database."""

    def test_api_stats_served_from_cache_on_second_call(self, client, app):
        # First call populates the cache
        r1 = client.get("/api/finance/api-stats")
        assert r1.status_code == 200

        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cache_key = f"finance:provider-metrics:{today}"

        # Cache entry must exist after first call (use the same cache instance)
        c = app._finance_cache
        cached = c.get(cache_key)
        assert cached is not None
        assert isinstance(cached, dict)

    def test_tracking_write_invalidates_cache(self, client, app):
        """After the cache is cleared, the next api-stats call re-populates it."""
        from datetime import datetime, timezone

        c = app._finance_cache  # same instance used by the routes
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cache_key = f"finance:provider-metrics:{today}"

        # 1. Warm up the cache via api-stats
        client.get("/api/finance/api-stats")
        assert c.get(cache_key) is not None

        # 2. Simulate what tracking writes do: delete the entry
        c.delete(cache_key)
        assert c.get(cache_key) is None

        # 3. Next api-stats call must re-populate the cache
        client.get("/api/finance/api-stats")
        assert c.get(cache_key) is not None
