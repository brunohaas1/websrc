"""Tests for app.security module."""

from __future__ import annotations

from app.security import (
    is_safe_http_url,
    sanitize_optional_selector,
    sanitize_text,
)


# ── sanitize_text ──────────────────────────────────────────────

def test_sanitize_text_escapes_html():
    assert "&lt;script&gt;" in sanitize_text("<script>alert(1)</script>")


def test_sanitize_text_collapses_whitespace():
    assert sanitize_text("hello   world") == "hello world"


def test_sanitize_text_respects_max_len():
    result = sanitize_text("a" * 300, max_len=250)
    assert len(result) == 250


def test_sanitize_text_strips_edges():
    assert sanitize_text("  hi  ") == "hi"


# ── sanitize_optional_selector ─────────────────────────────────

def test_selector_none_returns_none():
    assert sanitize_optional_selector(None) is None


def test_selector_empty_returns_none():
    assert sanitize_optional_selector("") is None


def test_selector_truncates_long():
    assert len(sanitize_optional_selector("x" * 200)) == 120


def test_selector_preserves_short():
    assert sanitize_optional_selector(".price") == ".price"


# ── is_safe_http_url ──────────────────────────────────────────

def test_http_url_accepted():
    assert is_safe_http_url("http://example.com") is True


def test_https_url_accepted():
    assert is_safe_http_url("https://example.com/path?q=1") is True


def test_ftp_url_rejected():
    assert is_safe_http_url("ftp://example.com") is False


def test_javascript_url_rejected():
    assert is_safe_http_url("javascript:alert(1)") is False


def test_empty_url_rejected():
    assert is_safe_http_url("") is False


def test_bare_path_rejected():
    assert is_safe_http_url("/just/a/path") is False


# ── require_admin_key ─────────────────────────────────────────

def test_admin_key_rejects_unauthorized(client, app):
    app.config["ADMIN_API_KEY"] = "secret-key-123"
    resp = client.post("/api/run-now")
    assert resp.status_code == 401


def test_admin_key_accepts_valid_header(client, app):
    app.config["ADMIN_API_KEY"] = "secret-key-123"
    resp = client.post(
        "/api/run-now",
        headers={"X-Admin-Key": "secret-key-123"},
    )
    assert resp.status_code != 401


def test_admin_key_accepts_query_param(client, app):
    app.config["ADMIN_API_KEY"] = "secret-key-123"
    resp = client.post("/api/run-now?admin_key=secret-key-123")
    assert resp.status_code != 401


def test_admin_key_skipped_when_not_configured(client, app):
    app.config["ADMIN_API_KEY"] = ""
    resp = client.post("/api/run-now")
    # Without a key configured, auth is bypassed (might be 503 but not 401)
    assert resp.status_code != 401
