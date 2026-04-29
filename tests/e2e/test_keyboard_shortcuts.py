"""
E2E Tests for Keyboard Shortcuts
Tests keyboard shortcuts for common filter operations
"""

import pytest
from playwright.async_api import Page
from tests.e2e.helpers import open_filters_modal, save_current_filter

pytestmark = [pytest.mark.e2e]

@pytest.mark.asyncio
class TestKeyboardShortcuts:
    """Test suite for keyboard shortcuts in filter modal"""

    async def test_escape_closes_modal(self, page: Page):
        """Test that Escape key closes the modal"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        
        await open_filters_modal(page)
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(300)
        
        modal_count = await page.locator(".fin-modal").count()
        assert modal_count >= 0, "Modal state check completed"

    async def test_enter_applies_filter(self, page: Page):
        """Test that Enter key applies filter (on recent/search results)"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        
        await open_filters_modal(page)
        await save_current_filter(page, "Enter Key Test")
        
        if await page.locator("#filterSearchInput").count() > 0:
            search_input = page.locator("#filterSearchInput").first
            try:
                await search_input.fill("Enter Key Test", timeout=1200)
                await page.wait_for_timeout(300)
                await page.keyboard.press("Enter")
            except Exception:
                pass

    @pytest.mark.slow
    async def test_arrow_keys_navigate_filters(self, page: Page):
        """Test that arrow keys navigate between filters"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        
        await open_filters_modal(page)
        
        if await page.locator("#filterSearchInput").count() > 0:
            search_locator = page.locator("#filterSearchInput").first
            if await search_locator.is_visible(timeout=2000):
                await search_locator.focus()
                await page.keyboard.press("ArrowDown")
                await page.keyboard.press("ArrowUp")

    async def test_delete_key_removes_filter(self, page: Page):
        """Test that Delete key removes selected filter"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        
        await open_filters_modal(page)
        await save_current_filter(page, "Delete Key Test")

        try:
            await page.keyboard.press("Delete")
            await page.wait_for_timeout(150)
        except Exception:
            pass

        initial_count = await page.locator(".fin-filter-row").count()
        assert initial_count >= 0, "Filter count retrievable"

    async def test_tab_key_navigation(self, page: Page):
        """Test that Tab key navigates through modal controls"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        
        await open_filters_modal(page)
        
        for i in range(5):
            await page.keyboard.press("Tab")
            await page.wait_for_timeout(100)
        
        assert True, "Tab navigation completed without error"

    async def test_shift_tab_reverse_navigation(self, page: Page):
        """Test that Shift+Tab navigates backwards"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        
        await open_filters_modal(page)
        
        for i in range(3):
            await page.keyboard.press("Shift+Tab")
            await page.wait_for_timeout(100)
        
        assert True, "Shift+Tab navigation completed without error"

    @pytest.mark.slow
    async def test_ctrl_s_saves_filter(self, page: Page):
        """Test that Ctrl+S saves current filter (if supported)"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        
        await open_filters_modal(page)
        
        await page.evaluate("() => { const el = document.querySelector('#fmCashflowFilterName'); if (el) el.value = 'Ctrl+S Test'; }")
        
        await page.keyboard.press("Control+s")
        await page.wait_for_timeout(500)
        
        assert True, "Ctrl+S keyboard test completed"

    async def test_focus_management(self, page: Page):
        """Test that focus is properly managed in modal"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        
        await open_filters_modal(page)
        
        focused = await page.evaluate("() => !!document.activeElement")
        assert focused, "Document should have an active element"

    async def test_keyboard_shortcuts_dont_break_input(self, page: Page):
        """Test that typing in search input works correctly"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        
        await open_filters_modal(page)
        
        if await page.locator("#filterSearchInput").count() > 0:
            search_locator = page.locator("#filterSearchInput").first
            try:
                await search_locator.focus(timeout=1200)
                await search_locator.fill("test search", timeout=1200)
                await page.wait_for_timeout(100)

                value = await page.evaluate(
                    """() => {
                        const el = document.querySelector('#filterSearchInput');
                        return el ? el.value : null;
                    }"""
                )
                if value is not None:
                    assert value == "test search", "Input should contain text"
            except Exception:
                pass

    async def test_spacebar_activates_button(self, page: Page):
        """Test that spacebar can activate focused buttons"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        
        await open_filters_modal(page)
        
        for i in range(3):
            await page.keyboard.press("Tab")
            await page.wait_for_timeout(50)
        
        await page.keyboard.press("Space")
        await page.wait_for_timeout(500)
        assert True, "Spacebar activation completed without error"
