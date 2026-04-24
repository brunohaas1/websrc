"""Playwright E2E tests for finance dashboard flows."""

from __future__ import annotations

import multiprocessing
import time

import pytest


def _has_playwright() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def _run_server(port: int) -> None:
    import os
    import tempfile

    db_path = os.path.join(tempfile.mkdtemp(), "e2e_finance_test.db")
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
    port = 5200
    proc = multiprocessing.Process(target=_run_server, args=(port,), daemon=True)
    proc.start()

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


@pytest.mark.skipif(not _has_playwright(), reason="playwright not installed")
class TestFinanceE2E:
    def test_finance_page_loads(self, live_server, page):
        page.goto(f"{live_server}/finance")
        page.wait_for_selector("#finPortfolioContent", timeout=15000)
        assert "Financeiro" in page.title() or "Financeiro" in page.inner_text("h1")

    def test_auto_refresh_and_filters_exist(self, live_server, page):
        page.goto(f"{live_server}/finance")
        page.wait_for_selector("#autoRefreshSelect", timeout=10000)
        assert page.locator("#autoRefreshSelect").is_visible()
        page.wait_for_selector("#txFilterType", timeout=15000)
        assert page.locator("#txFilterType").is_visible()

    def test_open_add_transaction_modal(self, live_server, page):
        page.goto(f"{live_server}/finance")
        page.wait_for_selector("#btnAddTransaction", timeout=10000)
        page.click("#btnAddTransaction")
        page.wait_for_selector("#finModalOverlay", timeout=10000)
        modal_title = page.locator("#finModalTitle")
        assert modal_title.is_visible()
