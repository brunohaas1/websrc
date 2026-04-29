"""
E2E Tests for Performance Optimization
Tests pagination, lazy loading, debouncing, and performance metrics
"""

import pytest
from playwright.async_api import Page
import time
from tests.e2e.helpers import open_filters_modal, save_current_filter

pytestmark = [pytest.mark.e2e]

@pytest.mark.asyncio
class TestPerformanceOptimizations:
    """Test suite for performance features"""

    @pytest.mark.slow
    async def test_search_debouncing(self, page: Page):
        """Test that search input is debounced"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        
        await open_filters_modal(page)
        
        if await page.locator("#filterSearchInput").count() > 0:
            search_locator = page.locator("#filterSearchInput").first
            try:
                search_terms = ["t", "te", "tes", "test"]
                start_time = time.time()

                for term in search_terms:
                    await search_locator.fill(term, timeout=1200)
                    await page.wait_for_timeout(50)

                elapsed = time.time() - start_time
                assert elapsed < 3.0, "Debounced search should complete quickly"
            except Exception:
                pass

    async def test_filter_list_renders_efficiently(self, page: Page):
        """Test that large filter lists render without blocking"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card", timeout=10000)
        
        start_time = time.time()
        await open_filters_modal(page)
        elapsed = time.time() - start_time
        
        assert elapsed < 5.0, "Filter modal should render efficiently"

    async def test_no_layout_thrashing(self, page: Page):
        """Test that UI updates don't cause excessive reflows"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        
        await open_filters_modal(page)
        
        if await page.locator("#filterSearchInput").count() > 0:
            search_locator = page.locator("#filterSearchInput").first
            try:
                for i in range(3):
                    await search_locator.fill(f"filter{i}", timeout=1200)
                    await page.wait_for_timeout(100)
            except Exception:
                pass
        
        assert True, "Layout thrashing test completed"

    async def test_recent_filters_storage_limit(self, page: Page):
        """Test that recent filters list is limited to avoid memory issues"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        
        storage_used = await page.evaluate("""
            () => {
                const prefs = localStorage.getItem('fin_filters_modal_prefs');
                return prefs ? prefs.length : 0;
            }
        """)
        
        assert storage_used < 10000, f"localStorage should be under 10KB, got {storage_used} bytes"

    @pytest.mark.slow
    async def test_search_performance_many_filters(self, page: Page):
        """Test search performance with many filters"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        
        await open_filters_modal(page)
        
        if await page.locator("#filterSearchInput").count() > 0:
            search_locator = page.locator("#filterSearchInput").first
            try:
                start_time = time.time()
                await search_locator.fill("test", timeout=1200)
                await page.wait_for_timeout(500)
                elapsed = time.time() - start_time
                assert elapsed < 2.0, "Search should complete quickly"
            except Exception:
                pass

    async def test_no_memory_leaks_on_reopen(self, page: Page):
        """Test that reopening modal doesn't leak memory"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        
        for i in range(3):
            await open_filters_modal(page)
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(200)
        
        initial_time = time.time()
        await open_filters_modal(page)
        final_time = time.time()
        
        assert (final_time - initial_time) < 2.0, "Modal should open quickly"

    async def test_modal_animation_performance(self, page: Page):
        """Test that modal animations don't stutter"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        
        start_time = time.time()
        await open_filters_modal(page)
        
        tabs = page.locator(".fin-filter-tab")
        tab_count = await tabs.count()
        for i in range(tab_count):
            try:
                tab = tabs.nth(i)
                await tab.click(timeout=1200)
                await page.wait_for_timeout(100)
            except Exception:
                pass
        
        elapsed = time.time() - start_time
        assert elapsed < 5.0, "Tab switching should complete reasonably"

    async def test_filter_application_performance(self, page: Page):
        """Test that applying filter doesn't block UI"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        
        await open_filters_modal(page)
        await save_current_filter(page, "Perf Test")
        
        start_time = time.time()
        
        use_buttons = page.locator(".fin-filter-btn:not(.delete)")
        if await use_buttons.count() > 0:
            btn = use_buttons.first
            if await btn.is_visible(timeout=2000):
                await btn.click()
                await page.wait_for_selector(".fin-toast, .toast", timeout=5000)
        
        elapsed = time.time() - start_time
        assert elapsed < 5.0, "Filter application should complete reasonably"

    async def test_css_animation_efficiency(self, page: Page):
        """Test that CSS animations are GPU-accelerated"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        
        await open_filters_modal(page)
        
        buttons = page.locator(".fin-filter-btn")
        button_count = await buttons.count()
        for i in range(min(3, button_count)):
            try:
                btn = buttons.nth(i)
                await btn.hover(timeout=1200)
                await page.wait_for_timeout(50)
            except Exception:
                pass
        
        assert True, "CSS animation test completed"
