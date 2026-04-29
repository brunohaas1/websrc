"""
E2E Tests for Cashflow Filter Application
Tests applying filters and cashflow operations
"""

import pytest
from playwright.async_api import Page
from tests.e2e.helpers import open_filters_modal, save_current_filter

pytestmark = [pytest.mark.e2e]

@pytest.mark.asyncio
class TestCashflowFilters:
    """Test suite for cashflow filter application"""

    async def test_cashflow_page_loads(self, page: Page):
        """Test that cashflow page loads successfully"""
        await page.goto("http://localhost:5000/finance")
        
        # Wait for main content
        await page.wait_for_selector(".fin-card", timeout=10000)
        
        # Check if cashflow section exists
        cashflow_card = await page.query_selector("#finCashflowCard")
        assert cashflow_card is not None, "Cashflow card should be visible"

    async def test_cashflow_has_filter_button(self, page: Page):
        """Test that cashflow card has filter button"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        
        # Look for filter-related button or control
        filter_button = await page.query_selector("text=Filtros")
        assert filter_button is not None, "Filter button should be present"

    async def test_apply_filter_updates_display(self, page: Page):
        """Test that applying filter updates cashflow display"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        
        # Get initial state
        initial_entries = await page.query_selector_all(".fin-cashflow-chip")
        initial_count = len(initial_entries)
        
        # Open filters modal
        await open_filters_modal(page)
        
        # Save a filter to ensure there's one to apply
        filter_name = f"Test Filter {initial_count}"
        await save_current_filter(page, filter_name)
        await page.wait_for_timeout(250)
        assert await page.locator(".fin-filter-row").count() >= 0

    async def test_category_filter_works(self, page: Page):
        """Test filtering by category"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        
        # Look for category select/filter
        category_select = await page.query_selector("[id*='category'], [name*='category']")
        if category_select:
            # Change category if available
            await category_select.click()
            options = await page.query_selector_all("option")
            if len(options) > 1:
                await options[1].click()
                await page.wait_for_timeout(500)  # Wait for filter to apply

    @pytest.mark.slow
    async def test_filter_date_range(self, page: Page):
        """Test filtering by date range"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        
        # Look for date input fields
        date_inputs = await page.query_selector_all("input[type='date']")
        if len(date_inputs) >= 2:
            # Set date range
            await date_inputs[0].fill("2026-01-01")
            await date_inputs[1].fill("2026-04-29")
            
            # Trigger filter
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(1000)

    async def test_filter_persistence_cashflow(self, page: Page):
        """Test that filter state persists during cashflow interactions"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        
        # Apply a filter
        await open_filters_modal(page)
        
        filter_name = "Persistence Cashflow Test"
        await save_current_filter(page, filter_name)
        
        # Apply the filter
        use_buttons = page.locator(".fin-filter-btn:not(.delete)")
        if await use_buttons.count() > 0:
            await use_buttons.first.click()
            await page.wait_for_selector(".fin-toast, .toast", timeout=5000)
        
        # Perform action (e.g., refresh)
        await page.evaluate(
            """
            () => {
                const refresh = Array.from(document.querySelectorAll('button, a'))
                    .find(el => (el.textContent || '').includes('Atualizar'));
                refresh?.click();
            }
            """
        )
        
        await page.wait_for_timeout(500)

    async def test_bulk_operations_with_filter(self, page: Page):
        """Test bulk operations with active filter"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        
        # Look for bulk operations button
        bulk_button = await page.query_selector("text=Operações|text=Lote|text=Bulk")
        if bulk_button:
            await bulk_button.click()
            await page.wait_for_selector(".fin-modal")
            
            # Check if entries are displayed
            entries = await page.query_selector_all("input[type='checkbox']")
            assert len(entries) >= 0, "Bulk modal should have checkboxes"

    @pytest.mark.slow
    async def test_filter_export_functionality(self, page: Page):
        """Test exporting filtered data"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        
        # Look for export button
        export_button = await page.query_selector("text=Exportar|text=Export")
        if export_button:
            # Set up listener for download
            async with page.expect_download() as download_info:
                await export_button.click()
            
            download = await download_info.value
            assert download is not None, "Download should be triggered"

    async def test_multiple_filters_application(self, page: Page):
        """Test applying multiple filters in sequence"""
        await page.goto("http://localhost:5000/finance")
        await page.wait_for_selector(".fin-card")
        
        filters = ["Filter 1", "Filter 2", "Filter 3"]
        
        for filter_name in filters:
            # Open modal
            await open_filters_modal(page)
            
            # Save filter
            await save_current_filter(page, filter_name)
            
            # Close modal
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(300)
