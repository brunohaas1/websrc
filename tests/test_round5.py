"""Tests for Round 5 features (16 new endpoints)."""

from __future__ import annotations


# ── System Uptime (#1) ──────────────────────────────────────────

def test_system_uptime_returns_services(client):
    resp = client.get("/api/system/uptime")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "boot_time" in data
    assert "uptime_seconds" in data
    assert "services" in data
    assert "api" in data["services"]
    assert data["services"]["api"]["status"] == "ok"


# ── Log Viewer (#2) ────────────────────────────────────────────

def test_logs_requires_no_admin_when_key_empty(client):
    """With ADMIN_API_KEY='', the endpoint should be accessible."""
    resp = client.get("/api/logs")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "entries" in data
    assert "total" in data


def test_logs_filter_by_level(client):
    resp = client.get("/api/logs?level=ERROR&limit=10")
    assert resp.status_code == 200


# ── Workers (#3) ───────────────────────────────────────────────

def test_workers_queue_disabled(client):
    resp = client.get("/api/workers")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "message" in data or "workers" in data


# ── Cache Stats (#4) ───────────────────────────────────────────

def test_cache_stats_returns_json(client):
    resp = client.get("/api/cache/stats")
    assert resp.status_code == 200
    assert isinstance(resp.get_json(), dict)


# ── Shareable Dashboard (#5) ──────────────────────────────────

def test_create_share_link(client):
    resp = client.post("/api/share", json={"label": "Test share", "hours": 24})
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["ok"] is True
    assert "token" in data
    assert "expires_at" in data


def test_list_shares(client):
    client.post("/api/share", json={"label": "S1"})
    resp = client.get("/api/shares")
    assert resp.status_code == 200
    shares = resp.get_json()
    assert isinstance(shares, list)
    assert len(shares) >= 1


def test_delete_share(client):
    cr = client.post("/api/share", json={"label": "To delete"})
    share_id = cr.get_json()["id"]
    resp = client.delete(f"/api/shares/{share_id}")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_shared_dashboard_invalid_token(client):
    resp = client.get("/shared/nonexistent_token_xyz")
    assert resp.status_code == 404


def test_shared_dashboard_valid_token(client):
    cr = client.post("/api/share", json={"label": "View"})
    token = cr.get_json()["token"]
    resp = client.get(f"/shared/{token}")
    assert resp.status_code == 200


def test_shared_dashboard_data_valid(client):
    cr = client.post("/api/share", json={"label": "Data"})
    token = cr.get_json()["token"]
    resp = client.get(f"/api/shared/{token}/dashboard")
    assert resp.status_code == 200


def test_shared_dashboard_data_invalid(client):
    resp = client.get("/api/shared/invalid_token_abc/dashboard")
    assert resp.status_code == 404


# ── Notifications (#7) ─────────────────────────────────────────

def test_notifications_empty(client):
    resp = client.get("/api/notifications")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_unread_notification_count_zero(client):
    resp = client.get("/api/notifications/unread-count")
    assert resp.status_code == 200
    assert resp.get_json()["count"] == 0


def test_mark_all_notifications_read(client):
    resp = client.post("/api/notifications/mark-all-read")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


# ── AI Chat (#12) ──────────────────────────────────────────────

def test_ai_chat_disabled(client):
    resp = client.post("/api/ai-chat", json={"message": "Olá"})
    assert resp.status_code == 503
    assert "IA" in resp.get_json().get("error", "")


def test_ai_chat_missing_message(client):
    resp = client.post("/api/ai-chat", json={})
    # Either 400 (missing message) or 503 (AI disabled) depending on check order
    assert resp.status_code in (400, 503)


# ── Sentiment (#13) ────────────────────────────────────────────

def test_sentiment_not_found(client):
    resp = client.get("/api/items/999999/sentiment")
    assert resp.status_code == 404


def test_sentiment_for_existing_item(client, repo):
    repo.upsert_item({
        "title": "Excelente crescimento do mercado",
        "url": "https://example.com/good-news-sentiment",
        "source": "test",
        "item_type": "news",
        "summary": "Ótimo resultado",
    })
    # upsert returns bool; fetch the inserted item's id
    items = repo.list_items(limit=1, offset=0)
    item_id = items[0]["id"]
    resp = client.get(f"/api/items/{item_id}/sentiment")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["sentiment"] in ("positive", "negative", "neutral")


# ── Price Forecast (#14) ──────────────────────────────────────

def test_price_forecast_insufficient_data(client, repo):
    wid = repo.add_price_watch({
        "name": "Test Product",
        "product_url": "https://example.com/product",
        "css_selector": ".price",
        "target_price": 0,
    })
    resp = client.get(f"/api/price-forecast/{wid}")
    assert resp.status_code == 400
    assert "insuficientes" in resp.get_json().get("error", "").lower()


def test_price_forecast_with_data(client, repo):
    wid = repo.add_price_watch({
        "name": "Forecast Item",
        "product_url": "https://example.com/item-forecast",
        "css_selector": ".price",
        "target_price": 0,
    })
    # Insert enough price history
    for price in [100.0, 105.0, 110.0, 115.0, 120.0]:
        repo.record_price(wid, price)
    resp = client.get(f"/api/price-forecast/{wid}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["trend"] in ("up", "down", "stable")
    assert len(data["forecast_7d"]) == 7
    assert data["data_points"] == 5


# ── Price Tags (#15) ──────────────────────────────────────────

def test_update_price_watch_tags(client, repo):
    wid = repo.add_price_watch({
        "name": "Tagged Item",
        "product_url": "https://example.com/tagged",
        "css_selector": ".price",
        "target_price": 0,
    })
    resp = client.patch(f"/api/price-watch/{wid}/tags", json={"tags": ["eletrônico", "promoção"]})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_update_price_watch_tags_invalid(client, repo):
    wid = repo.add_price_watch({
        "name": "Bad Tags",
        "product_url": "https://example.com/bad-tags",
        "css_selector": ".price",
        "target_price": 0,
    })
    resp = client.patch(f"/api/price-watch/{wid}/tags", json={"tags": "not-a-list"})
    assert resp.status_code == 400


# ── Webhooks (#16) ─────────────────────────────────────────────

def test_list_webhooks_empty(client):
    resp = client.get("/api/webhooks")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_add_webhook_happy(client):
    resp = client.post("/api/webhooks", json={
        "name": "My Hook",
        "url": "https://example.com/hook",
        "event_types": ["alert"],
    })
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["ok"] is True
    assert "id" in data


def test_add_webhook_missing_fields(client):
    resp = client.post("/api/webhooks", json={"name": ""})
    assert resp.status_code == 400


def test_add_webhook_invalid_url(client):
    resp = client.post("/api/webhooks", json={
        "name": "Bad URL",
        "url": "ftp://not-http.com",
    })
    assert resp.status_code == 400


def test_delete_webhook(client):
    cr = client.post("/api/webhooks", json={
        "name": "Delete Me",
        "url": "https://example.com/delete",
    })
    wh_id = cr.get_json()["id"]
    resp = client.delete(f"/api/webhooks/{wh_id}")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


# ── Layout Presets (#6) ────────────────────────────────────────

def test_layout_presets(client):
    resp = client.get("/api/layout-presets")
    assert resp.status_code == 200
    presets = resp.get_json()
    assert isinstance(presets, list)
    assert len(presets) >= 4
    ids = {p["id"] for p in presets}
    assert {"default", "compact", "analytics", "minimal"} <= ids


# ── Events Calendar (#10) ─────────────────────────────────────

def test_events_calendar(client):
    resp = client.get("/api/events-calendar")
    assert resp.status_code == 200
    assert isinstance(resp.get_json(), list)


# ── Email Digest (#11) route exists ───────────────────────────

def test_email_digest_no_smtp(client):
    resp = client.post("/api/email-digest/send")
    assert resp.status_code == 503
    assert "SMTP" in resp.get_json().get("error", "")
