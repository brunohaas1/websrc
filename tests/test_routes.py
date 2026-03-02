"""Tests for app.routes endpoints."""

from __future__ import annotations


# ── basic endpoints ────────────────────────────────────────────

def test_index_returns_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"<html" in resp.data.lower() or b"<!doctype" in resp.data.lower()


def test_health_returns_status(client):
    resp = client.get("/health")
    data = resp.get_json()
    assert resp.status_code in (200, 207)
    assert "status" in data
    assert "checks" in data


def test_metrics_returns_prometheus(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert b"dashboard_http_requests_total" in resp.data


# ── dashboard ──────────────────────────────────────────────────

def test_dashboard_returns_expected_keys(client):
    resp = client.get("/api/dashboard")
    data = resp.get_json()
    assert resp.status_code == 200
    for key in ("news", "promotions", "prices", "weather",
                "tech_ai", "videos", "releases", "jobs",
                "alerts", "ai_observability"):
        assert key in data, f"missing key: {key}"


# ── items ──────────────────────────────────────────────────────

def test_items_returns_list(client):
    resp = client.get("/api/items?type=news&limit=5")
    assert resp.status_code == 200
    assert isinstance(resp.get_json(), list)


def test_items_limit_clamped(client):
    resp = client.get("/api/items?limit=9999")
    assert resp.status_code == 200


# ── ai-observability ──────────────────────────────────────────

def test_ai_observability_has_structure(client):
    resp = client.get("/api/ai-observability")
    data = resp.get_json()
    assert resp.status_code == 200
    assert "total_items" in data
    assert "enriched_items" in data
    assert "fallback_rate_by_hour" in data
    assert "source_accuracy" in data
    assert "reason_breakdown" in data


# ── price-watch ────────────────────────────────────────────────

def test_price_watch_missing_fields(client):
    resp = client.post("/api/price-watch", json={})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_price_watch_invalid_url(client):
    resp = client.post("/api/price-watch", json={
        "name": "Test",
        "product_url": "ftp://bad",
        "target_price": 100.0,
    })
    assert resp.status_code == 400


def test_price_watch_happy_path(client):
    resp = client.post("/api/price-watch", json={
        "name": "Monitor LG",
        "product_url": "https://store.example.com/item/123",
        "target_price": 999.90,
    })
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["ok"] is True
    assert "id" in data
