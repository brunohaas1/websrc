"""E2E Test Configuration for Playwright."""

from __future__ import annotations

import multiprocessing
import os
import tempfile
import time
import urllib.request

import pytest
import pytest_asyncio
from playwright.async_api import Browser, BrowserContext, async_playwright


# Test configuration
TEST_HOST = "127.0.0.1"
TEST_PORT = 5000
TEST_URL = f"http://{TEST_HOST}:{TEST_PORT}"


def _run_server(port: int) -> None:
    """Start Flask dev-server in a separate process for E2E tests."""
    db_path = os.path.join(tempfile.mkdtemp(), "e2e_test.db")
    os.environ["DATABASE_URL"] = ""
    os.environ["DATABASE_PATH"] = db_path
    os.environ["QUEUE_ENABLED"] = "0"
    os.environ["AI_LOCAL_ENABLED"] = "0"
    os.environ["LOG_JSON"] = "0"
    os.environ["ADMIN_API_KEY"] = ""
    os.environ["FINANCE_API_KEY"] = ""

    from app import create_app

    app = create_app(start_scheduler=False)
    app.run(host=TEST_HOST, port=port, use_reloader=False)


@pytest.fixture(scope="session")
def flask_server():
    """Start Flask server for E2E tests"""
    try:
        urllib.request.urlopen(f"{TEST_URL}/health", timeout=1)
    except Exception:
        pass
    else:
        yield TEST_URL
        return

    proc = multiprocessing.Process(target=_run_server, args=(TEST_PORT,), daemon=True)
    proc.start()

    for _ in range(80):
        try:
            urllib.request.urlopen(f"{TEST_URL}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    else:
        proc.kill()
        proc.join(timeout=3)
        raise RuntimeError("Failed to start Flask server for E2E tests")

    yield TEST_URL

    proc.kill()
    proc.join(timeout=3)


@pytest_asyncio.fixture
async def browser():
    """Create Playwright browser instance"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        yield browser
        await browser.close()


@pytest_asyncio.fixture
async def context(browser: Browser):
    """Create new browser context for each test"""
    context = await browser.new_context(
        viewport={"width": 1280, "height": 720},
        ignore_https_errors=True,
    )
    yield context
    await context.close()


@pytest_asyncio.fixture
async def page(context: BrowserContext, flask_server):
    """Create new page for each test"""
    page = await context.new_page()
    # Set viewport for consistent testing
    await page.set_viewport_size({"width": 1280, "height": 720})
    yield page
    await page.close()


@pytest.fixture
def event_loop():
    """Create event loop for async tests"""
    import asyncio

    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# Marker registration
def pytest_configure(config):
    """Register custom markers"""
    config.addinivalue_line("markers", "e2e: mark test as E2E test")
    config.addinivalue_line("markers", "slow: mark test as slow running")
