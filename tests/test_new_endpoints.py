"""Tests for all new endpoints added in feature rounds."""

from __future__ import annotations


# ── Custom Feeds CRUD ──────────────────────────────────────────

def test_list_custom_feeds_empty(client):
    resp = client.get("/api/custom-feeds")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_add_custom_feed_happy(client):
    resp = client.post("/api/custom-feeds", json={
        "name": "Tech Feed",
        "feed_url": "https://example.com/rss.xml",
    })
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["ok"] is True
    assert "id" in data


def test_add_custom_feed_missing_fields(client):
    resp = client.post("/api/custom-feeds", json={"name": ""})
    assert resp.status_code == 400


def test_add_custom_feed_invalid_url(client):
    resp = client.post("/api/custom-feeds", json={
        "name": "Bad",
        "feed_url": "ftp://bad.com",
    })
    assert resp.status_code == 400


def test_delete_custom_feed(client):
    resp = client.post("/api/custom-feeds", json={
        "name": "ToDelete",
        "feed_url": "https://example.com/feed.xml",
    })
    feed_id = resp.get_json()["id"]
    del_resp = client.delete(f"/api/custom-feeds/{feed_id}")
    assert del_resp.status_code == 200
    assert del_resp.get_json()["ok"] is True


def test_toggle_custom_feed(client):
    resp = client.post("/api/custom-feeds", json={
        "name": "Toggle Me",
        "feed_url": "https://example.com/toggle.xml",
    })
    feed_id = resp.get_json()["id"]
    toggle_resp = client.patch(
        f"/api/custom-feeds/{feed_id}/toggle",
        json={"active": False},
    )
    assert toggle_resp.status_code == 200


# ── Favorites CRUD ─────────────────────────────────────────────

def test_list_favorites_empty(client):
    resp = client.get("/api/favorites")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_add_favorite(client, repo, sample_item):
    repo.upsert_item(sample_item)
    items = repo.list_items(item_type="news")
    item_id = items[0]["id"]

    resp = client.post("/api/favorites", json={"item_id": item_id})
    assert resp.status_code == 201
    assert resp.get_json()["ok"] is True


def test_add_favorite_missing_item_id(client):
    resp = client.post("/api/favorites", json={})
    assert resp.status_code == 400


def test_remove_favorite(client, repo, sample_item):
    repo.upsert_item(sample_item)
    items = repo.list_items(item_type="news")
    item_id = items[0]["id"]

    client.post("/api/favorites", json={"item_id": item_id})
    del_resp = client.delete(f"/api/favorites/{item_id}")
    assert del_resp.status_code == 200


def test_update_favorite_tags(client, repo, sample_item):
    repo.upsert_item(sample_item)
    items = repo.list_items(item_type="news")
    item_id = items[0]["id"]

    client.post("/api/favorites", json={"item_id": item_id})
    resp = client.patch(
        f"/api/favorites/{item_id}/tags",
        json={"tags": ["tech", "important"]},
    )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


# ── Notes CRUD ─────────────────────────────────────────────────

def test_list_notes_empty(client):
    resp = client.get("/api/notes")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_add_note(client, repo, sample_item):
    repo.upsert_item(sample_item)
    items = repo.list_items(item_type="news")
    item_id = items[0]["id"]

    resp = client.post("/api/notes", json={
        "item_id": item_id,
        "content": "This is a test note.",
    })
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["ok"] is True
    assert "id" in data


def test_add_note_missing_content(client, repo, sample_item):
    repo.upsert_item(sample_item)
    items = repo.list_items(item_type="news")
    resp = client.post("/api/notes", json={
        "item_id": items[0]["id"],
        "content": "",
    })
    assert resp.status_code == 400


def test_update_note(client, repo, sample_item):
    repo.upsert_item(sample_item)
    items = repo.list_items(item_type="news")
    item_id = items[0]["id"]

    resp = client.post("/api/notes", json={
        "item_id": item_id,
        "content": "Original note",
    })
    note_id = resp.get_json()["id"]

    patch_resp = client.patch(
        f"/api/notes/{note_id}",
        json={"content": "Updated note"},
    )
    assert patch_resp.status_code == 200


def test_delete_note(client, repo, sample_item):
    repo.upsert_item(sample_item)
    items = repo.list_items(item_type="news")
    item_id = items[0]["id"]

    resp = client.post("/api/notes", json={
        "item_id": item_id,
        "content": "To delete",
    })
    note_id = resp.get_json()["id"]

    del_resp = client.delete(f"/api/notes/{note_id}")
    assert del_resp.status_code == 200


# ── Service Monitors CRUD ─────────────────────────────────────

def test_list_service_monitors_empty(client):
    resp = client.get("/api/service-monitors")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_add_service_monitor(client):
    resp = client.post("/api/service-monitors", json={
        "name": "Google",
        "url": "https://www.google.com",
    })
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["ok"] is True
    assert "id" in data


def test_add_service_monitor_invalid_url(client):
    resp = client.post("/api/service-monitors", json={
        "name": "Bad",
        "url": "not-a-url",
    })
    assert resp.status_code == 400


def test_add_service_monitor_missing_name(client):
    resp = client.post("/api/service-monitors", json={
        "name": "",
        "url": "https://example.com",
    })
    assert resp.status_code == 400


def test_delete_service_monitor(client):
    resp = client.post("/api/service-monitors", json={
        "name": "ToDelete",
        "url": "https://example.com/health",
    })
    monitor_id = resp.get_json()["id"]
    del_resp = client.delete(f"/api/service-monitors/{monitor_id}")
    assert del_resp.status_code == 200


def test_service_monitor_history(client):
    resp = client.post("/api/service-monitors", json={
        "name": "HistTest",
        "url": "https://example.com",
    })
    monitor_id = resp.get_json()["id"]
    hist_resp = client.get(f"/api/service-monitors/{monitor_id}/history")
    assert hist_resp.status_code == 200
    assert isinstance(hist_resp.get_json(), list)


# ── Currency Rates ─────────────────────────────────────────────

def test_list_currency_rates(client):
    resp = client.get("/api/currency-rates")
    assert resp.status_code == 200
    assert isinstance(resp.get_json(), list)


# ── Daily Digest ───────────────────────────────────────────────

def test_get_daily_digest(client):
    resp = client.get("/api/daily-digest")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "content" in data


# ── Trending Topics ────────────────────────────────────────────

def test_get_trending(client):
    resp = client.get("/api/trending")
    assert resp.status_code == 200
    assert isinstance(resp.get_json(), list)


# ── Saved Filters ─────────────────────────────────────────────

def test_list_saved_filters_empty(client):
    resp = client.get("/api/saved-filters")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_add_saved_filter(client):
    resp = client.post("/api/saved-filters", json={
        "name": "My Filter",
        "filter": {"query": "python", "jobFilter": "remote"},
    })
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["ok"] is True
    assert "id" in data


def test_add_saved_filter_missing_name(client):
    resp = client.post("/api/saved-filters", json={
        "name": "",
        "filter": {},
    })
    assert resp.status_code == 400


def test_delete_saved_filter(client):
    resp = client.post("/api/saved-filters", json={
        "name": "ToDelete",
        "filter": {"query": "test"},
    })
    filter_id = resp.get_json()["id"]
    del_resp = client.delete(f"/api/saved-filters/{filter_id}")
    assert del_resp.status_code == 200


# ── Push Notifications ─────────────────────────────────────────

def test_push_subscribe(client):
    resp = client.post("/api/push/subscribe", json={
        "endpoint": "https://push.example.com/v1/sub123",
        "keys": {"p256dh": "abc", "auth": "xyz"},
    })
    assert resp.status_code == 201
    assert resp.get_json()["ok"] is True


def test_push_subscribe_missing_endpoint(client):
    resp = client.post("/api/push/subscribe", json={})
    assert resp.status_code == 400


def test_push_unsubscribe(client):
    endpoint = "https://push.example.com/v1/unsub123"
    client.post("/api/push/subscribe", json={
        "endpoint": endpoint,
        "keys": {"p256dh": "abc", "auth": "xyz"},
    })
    resp = client.post("/api/push/unsubscribe", json={
        "endpoint": endpoint,
    })
    assert resp.status_code == 200


def test_push_unsubscribe_missing_endpoint(client):
    resp = client.post("/api/push/unsubscribe", json={})
    assert resp.status_code == 400


def test_vapid_public_key(client):
    resp = client.get("/api/push/vapid-public-key")
    assert resp.status_code == 200
    assert "publicKey" in resp.get_json()


# ── Price Watch DELETE / PATCH ─────────────────────────────────

def test_delete_price_watch(client):
    add_resp = client.post("/api/price-watch", json={
        "name": "ToDelete",
        "product_url": "https://store.example.com/del/1",
        "target_price": 50.0,
    })
    watch_id = add_resp.get_json()["id"]
    del_resp = client.delete(f"/api/price-watch/{watch_id}")
    assert del_resp.status_code == 200
    assert del_resp.get_json()["ok"] is True


def test_update_price_watch(client):
    add_resp = client.post("/api/price-watch", json={
        "name": "ToUpdate",
        "product_url": "https://store.example.com/upd/1",
        "target_price": 100.0,
    })
    watch_id = add_resp.get_json()["id"]
    patch_resp = client.patch(
        f"/api/price-watch/{watch_id}",
        json={"name": "Updated Name", "target_price": 75.0},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.get_json()["ok"] is True


def test_update_price_watch_empty_body(client):
    add_resp = client.post("/api/price-watch", json={
        "name": "EmptyPatch",
        "product_url": "https://store.example.com/ep/1",
        "target_price": 25.0,
    })
    watch_id = add_resp.get_json()["id"]
    patch_resp = client.patch(f"/api/price-watch/{watch_id}", json={})
    assert patch_resp.status_code == 400


# ── Price History ──────────────────────────────────────────────

def test_price_history_endpoint(client):
    add_resp = client.post("/api/price-watch", json={
        "name": "HistTest",
        "product_url": "https://store.example.com/hist/1",
        "target_price": 30.0,
    })
    watch_id = add_resp.get_json()["id"]
    resp = client.get(f"/api/price-history/{watch_id}")
    assert resp.status_code == 200
    assert isinstance(resp.get_json(), list)


# ── Export PDF ─────────────────────────────────────────────────

def test_export_pdf(client):
    resp = client.get("/api/export/pdf")
    assert resp.status_code == 200
    assert b"Dashboard Report" in resp.data


# ── OpenAPI / Swagger ──────────────────────────────────────────

def test_openapi_spec(client):
    resp = client.get("/api/openapi.json")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["openapi"] == "3.0.3"
    assert "paths" in data
    assert "/api/dashboard" in data["paths"]


def test_swagger_ui_html(client):
    resp = client.get("/docs")
    assert resp.status_code == 200
    assert b"swagger-ui" in resp.data


# ── LLM Status ─────────────────────────────────────────────────

def test_llm_status_disabled(client):
    resp = client.get("/api/llm-status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "disabled"


# ── Items pagination ───────────────────────────────────────────

def test_items_pagination(client, repo, sample_item):
    repo.upsert_item(sample_item)
    resp = client.get("/api/items?type=news&page=1&limit=10")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert data["page"] == 1


# ── RSS Feed Articles ──────────────────────────────────────────

def test_feed_articles_not_found(client):
    resp = client.get("/api/custom-feeds/9999/articles")
    assert resp.status_code == 404
    data = resp.get_json()
    assert "error" in data


def test_feed_articles_for_existing_feed(client):
    # First create a feed
    client.post("/api/custom-feeds", json={
        "name": "Test RSS",
        "feed_url": "https://example.com/rss.xml",
    })
    # Try to fetch articles (will fail network but endpoint should handle it)
    resp = client.get("/api/custom-feeds/1/articles")
    # Should be 502 (network fail) or 200 (if cached), not 500
    assert resp.status_code in (200, 502)


# ── Smart Alerts Analyze ───────────────────────────────────────

def test_smart_alerts_analyze(client):
    resp = client.post("/api/smart-alerts/analyze")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert "alerts" in data
    assert "count" in data
    assert isinstance(data["alerts"], list)
