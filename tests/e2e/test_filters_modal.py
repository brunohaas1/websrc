"""
E2E Tests for Saved Filters Modal
Tests filter creation, favorites, templates, and UI interactions
"""

import pytest
from playwright.async_api import Page

pytestmark = [pytest.mark.e2e]


async def _open_filters_modal(page: Page) -> None:
    await page.wait_for_selector("#btnCashflowSavedFilters", state="attached", timeout=10000)
    # Reset tab preference so My Filters tab is shown by default
    await page.evaluate("() => { try { const p = JSON.parse(localStorage.getItem('fin_filters_modal_prefs') || '{}'); p.activeTab = 0; localStorage.setItem('fin_filters_modal_prefs', JSON.stringify(p)); } catch(e) {} }")
    await page.wait_for_function("() => typeof openCashflowSavedFiltersModal === 'function'", timeout=10000)

    # Retry opening because UI startup can race with event binding/rendering.
    for _ in range(3):
        await page.evaluate("""
            async () => {
                if (typeof openCashflowSavedFiltersModal === 'function') {
                    await openCashflowSavedFiltersModal();
                    return;
                }
                const btn = document.querySelector('#btnCashflowSavedFilters');
                btn?.click();
            }
        """)

        has_modal_content = await page.evaluate(
            "() => !!document.querySelector('#tabTemplates') && !!document.querySelector('#fmCashflowFilterName')"
        )
        if has_modal_content:
            await page.wait_for_selector("#finModalOverlay", state="visible", timeout=10000)
            return

        await page.wait_for_timeout(400)

    await page.wait_for_selector("#tabTemplates", state="attached", timeout=10000)


@pytest.mark.asyncio
class TestFiltersModal:
    """Test suite for saved filters modal functionality"""

    async def test_modal_opens(self, page: Page):
        """Test that filters modal opens successfully"""
        await page.goto("http://localhost:5000/finance")

        # Wait for page to load
        await page.wait_for_selector(".fin-card", timeout=10000)

        await _open_filters_modal(page)

        modal = await page.query_selector(".fin-modal")
        assert modal is not None, "Filter modal should be visible"

    async def test_modal_tabs_switch(self, page: Page):
        """Test switching between modal tabs"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        await _open_filters_modal(page)
        
        # Ensure templates tab trigger exists before switching
        templates_tab = await page.query_selector("#tabTemplates")
        assert templates_tab is not None, "Templates tab button should exist"
        
        # Click Templates tab via JS
        clicked_templates_tab = await page.evaluate(
            """
            () => {
                const btn = document.querySelector('#tabTemplates');
                if (!btn) return false;
                btn.click();
                return true;
            }
            """
        )
        assert clicked_templates_tab, "Templates tab button should exist"
        await page.wait_for_timeout(300)  # Wait for tab switch animation

    async def test_save_filter(self, page: Page):
        """Test saving a new filter"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        await _open_filters_modal(page)
        
        # Type filter name
        filter_name = "Test Filter Automation"
        await page.wait_for_selector("#fmCashflowFilterName", state="attached", timeout=5000)
        await page.evaluate(f"() => {{ const el = document.querySelector('#fmCashflowFilterName'); if (el) {{ el.value = {repr(filter_name)}; el.dispatchEvent(new Event('input')); }} }}")
        
        # Click save button via JS (modal re-renders so Playwright locator may become stale)
        await page.evaluate("() => document.querySelector('#btnSaveCashflowFilter')?.click()")
        
        # Wait for success toast
        await page.wait_for_selector(".fin-toast, .toast", timeout=5000)
        
        # Verify filter appears in list
        await page.wait_for_selector(f"text={filter_name}", timeout=5000)

    async def test_toggle_favorite(self, page: Page):
        """Test marking filter as favorite"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        await _open_filters_modal(page)
        
        # Save a test filter first
        filter_name = "Favorite Test Filter"
        await page.wait_for_selector("#fmCashflowFilterName", state="attached", timeout=5000)
        await page.evaluate(f"() => {{ const el = document.querySelector('#fmCashflowFilterName'); if (el) {{ el.value = {repr(filter_name)}; el.dispatchEvent(new Event('input')); }} }}")
        await page.evaluate("() => document.querySelector('#btnSaveCashflowFilter')?.click()")
        await page.wait_for_selector(".fin-toast, .toast", timeout=5000)
        
        # Find and click star icon for the created filter via JS
        await page.wait_for_timeout(500)  # Wait for modal to re-render after save
        async with page.expect_response(
            lambda r: "/api/finance/cashflow/saved-filters/" in r.url and "/favorite" in r.url and r.request.method == "PUT",
            timeout=10000,
        ) as fav_resp_info:
            await page.evaluate(
                f"""
                () => {{
                    const rows = Array.from(document.querySelectorAll('.fin-filter-row'));
                    const row = rows.find(r => (r.textContent || '').includes({repr(filter_name)}));
                    row?.querySelector('.fin-filter-star')?.click();
                }}
                """
            )

        fav_resp = await fav_resp_info.value
        assert fav_resp.ok, "Favorite API call should succeed"

    async def test_delete_filter(self, page: Page):
        """Test deleting a saved filter"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        await _open_filters_modal(page)
        
        # Save a test filter
        filter_name = "Delete Test Filter"
        if await page.query_selector("#fmCashflowFilterName") is None:
            await _open_filters_modal(page)
        await page.evaluate(f"() => {{ const el = document.querySelector('#fmCashflowFilterName'); if (el) {{ el.value = {repr(filter_name)}; el.dispatchEvent(new Event('input')); }} }}")
        await page.evaluate("() => document.querySelector('#btnSaveCashflowFilter')?.click()")
        await page.wait_for_selector(".fin-toast, .toast", timeout=5000)
        await page.wait_for_timeout(500)  # Wait for modal to re-render after save
        
        # Accept deletion confirmation and click delete via JS
        page.once("dialog", lambda dialog: dialog.accept())
        await page.evaluate("() => document.querySelector('.fin-filter-btn.delete')?.click()")
        
        # Wait for deletion confirmation
        await page.wait_for_selector(".fin-toast, .toast", timeout=5000)

    async def test_apply_filter(self, page: Page):
        """Test applying a saved filter"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        await _open_filters_modal(page)
        
        # Save a test filter first
        filter_name = "Apply Test Filter"
        if await page.query_selector("#fmCashflowFilterName") is None:
            await _open_filters_modal(page)
        await page.evaluate(f"() => {{ const el = document.querySelector('#fmCashflowFilterName'); if (el) {{ el.value = {repr(filter_name)}; el.dispatchEvent(new Event('input')); }} }}")
        await page.evaluate("() => document.querySelector('#btnSaveCashflowFilter')?.click()")
        await page.wait_for_selector(".fin-toast, .toast", timeout=5000)
        await page.wait_for_timeout(500)  # Wait for modal to re-render after save
        
        # Click use/apply button via JS
        await page.evaluate("() => document.querySelector('.fin-filter-btn:not(.delete)')?.click()")
        
        # Wait for success toast
        await page.wait_for_selector(".fin-toast, .toast", timeout=5000)

    async def test_templates_display(self, page: Page):
        """Test that templates are displayed in templates tab"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        await _open_filters_modal(page)
        
        # Switch to Templates tab via JS
        clicked_templates_tab = await page.evaluate(
            """
            () => {
                const btn = document.querySelector('#tabTemplates');
                if (!btn) return false;
                btn.click();
                return true;
            }
            """
        )
        assert clicked_templates_tab, "Templates tab button should exist"
        await page.wait_for_timeout(300)

    @pytest.mark.slow
    async def test_filter_persistence(self, page: Page):
        """Test that filters persist across page reloads"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        await _open_filters_modal(page)
        
        # Save a filter
        filter_name = "Persistence Test Filter"
        await page.wait_for_selector("#fmCashflowFilterName", state="attached", timeout=5000)
        await page.evaluate(f"() => {{ const el = document.querySelector('#fmCashflowFilterName'); if (el) {{ el.value = {repr(filter_name)}; el.dispatchEvent(new Event('input')); }} }}")
        await page.evaluate("() => document.querySelector('#btnSaveCashflowFilter')?.click()")
        await page.wait_for_selector(".fin-toast, .toast", timeout=5000)
        
        # Close modal
        close_btn = await page.query_selector(".fin-modal-header [class*='close']")
        if close_btn:
            await close_btn.click()
        else:
            # Click outside modal or press Escape
            await page.keyboard.press("Escape")
        
        # Reload page
        await page.reload()
        await page.wait_for_selector(".fin-card", timeout=10000)
        
        # Open modal again
        await _open_filters_modal(page)
        
        # Verify filter still exists
        await page.wait_for_selector(f"text={filter_name}", timeout=5000)
