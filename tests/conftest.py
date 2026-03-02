"""Shared fixtures for the websrc test suite."""

from __future__ import annotations

import pytest


@pytest.fixture()
def app(tmp_path, monkeypatch):
    """Create a fresh Flask app backed by a temporary SQLite database."""
    db_path = str(tmp_path / "test.db")

    # Patch Config class attributes BEFORE create_app reads them
    monkeypatch.setattr("app.config.Config.DATABASE_URL", "")
    monkeypatch.setattr("app.config.Config.DATABASE_PATH", db_path)
    monkeypatch.setattr("app.config.Config.DATABASE_TARGET", db_path)
    monkeypatch.setattr("app.config.Config.QUEUE_ENABLED", False)
    monkeypatch.setattr("app.config.Config.AI_LOCAL_ENABLED", False)
    monkeypatch.setattr("app.config.Config.LOG_JSON", False)
    monkeypatch.setattr("app.config.Config.ADMIN_API_KEY", "")

    from app import create_app

    application = create_app(start_scheduler=False)
    application.config["TESTING"] = True
    yield application


@pytest.fixture()
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture()
def repo(app):
    """Repository wired to the test database."""
    from app.repository import Repository

    return Repository(app.config["DATABASE_TARGET"])


@pytest.fixture()
def sample_item():
    """Minimal valid item dict."""
    return {
        "item_type": "news",
        "source": "test-source",
        "title": "Test Article Title",
        "url": "https://example.com/article-1",
        "summary": "A test article summary.",
        "extra": {"ai_reason": "local-ai", "ai_summary": "resumo de teste"},
    }
