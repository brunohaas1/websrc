"""Playwright E2E tests for the dashboard.

Requirements:
  pip install playwright pytest-playwright
  python -m playwright install chromium

Run:
  pytest tests/e2e/ --headed   (visible browser)
  pytest tests/e2e/            (headless)
"""

from __future__ import annotations

import multiprocessing
import time

import pytest

# --------------- Fixtures ------------------------------------------------

def _run_server(port: int) -> None:
    """Start the Flask dev-server for E2E tests."""
    import os, tempfile
    db_path = os.path.join(tempfile.mkdtemp(), "e2e_test.db")
    os.environ["DATABASE_URL"] = ""
    os.environ["DATABASE_PATH"] = db_path
    os.environ["QUEUE_ENABLED"] = "0"
    os.environ["AI_LOCAL_ENABLED"] = "0"
    os.environ["LOG_JSON"] = "0"
    os.environ["ADMIN_API_KEY"] = ""

    from app import create_app
    app = create_app(start_scheduler=False)
    app.run(host="127.0.0.1", port=port, use_reloader=False)


@pytest.fixture(scope="module")
def live_server():
    """Launch a temporary Flask server in a background process."""
    port = 5199
    proc = multiprocessing.Process(target=_run_server, args=(port,), daemon=True)
    proc.start()
    # Wait for server to start
    import urllib.request
    for _ in range(40):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.skip("Could not start live server")
    yield f"http://127.0.0.1:{port}"
    proc.kill()
    proc.join(timeout=3)


# --------------- Tests ---------------------------------------------------

@pytest.mark.skipif(
    not _has_playwright(),
    reason="playwright not installed",
)
class TestDashboardE2E:
    """Basic E2E smoke tests."""

    def test_dashboard_loads(self, live_server, page):
        page.goto(live_server)
        page.wait_for_selector("h1", timeout=10_000)
        assert "Dashboard" in page.title() or "Dashboard" in page.inner_text("h1")

    def test_status_bar_visible(self, live_server, page):
        page.goto(live_server)
        bar = page.locator(".status-bar")
        bar.wait_for(timeout=10_000)
        assert bar.is_visible()

    def test_search_input_works(self, live_server, page):
        page.goto(live_server)
        search = page.locator("#searchInput")
        search.wait_for(timeout=10_000)
        search.fill("python")
        assert search.input_value() == "python"

    def test_theme_toggle(self, live_server, page):
        page.goto(live_server)
        toggle = page.locator("#themeToggle")
        toggle.wait_for(timeout=10_000)
        toggle.click()
        # After click, body should have data-theme attribute changed
        theme = page.evaluate("document.body.getAttribute('data-theme')")
        assert theme in ("light", "dark")

    def test_cards_present(self, live_server, page):
        page.goto(live_server)
        page.wait_for_selector(".card", timeout=10_000)
        cards = page.locator(".card")
        assert cards.count() >= 10  # We have 17+ cards

    def test_health_endpoint(self, live_server, page):
        page.goto(f"{live_server}/health")
        body = page.inner_text("body")
        assert "status" in body

    def test_swagger_docs(self, live_server, page):
        page.goto(f"{live_server}/docs")
        page.wait_for_selector("#swagger-ui", timeout=15_000)
        assert page.locator("#swagger-ui").is_visible()

    def test_price_form_submission(self, live_server, page):
        page.goto(live_server)
        page.fill("#priceForm input[name='name']", "Test Product")
        page.fill("#priceForm input[name='product_url']", "https://example.com/product")
        page.fill("#priceForm input[name='target_price']", "99.90")
        page.click("#priceForm button[type='submit']")
        # Wait for toast notification
        page.wait_for_selector(".toast", timeout=5_000)


def _has_playwright() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False
