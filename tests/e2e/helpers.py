"""Shared helpers for finance E2E tests."""

from playwright.async_api import Page


async def open_filters_modal(page: Page) -> None:
    await page.wait_for_selector("#btnCashflowSavedFilters", state="attached", timeout=10000)
    await page.evaluate(
        "() => { try { const p = JSON.parse(localStorage.getItem('fin_filters_modal_prefs') || '{}'); p.activeTab = 0; localStorage.setItem('fin_filters_modal_prefs', JSON.stringify(p)); } catch (e) {} }"
    )
    await page.wait_for_function("() => typeof openCashflowSavedFiltersModal === 'function'", timeout=10000)

    for _ in range(3):
        await page.evaluate(
            """
            async () => {
                if (typeof openCashflowSavedFiltersModal === 'function') {
                    await openCashflowSavedFiltersModal();
                    return;
                }
                const btn = document.querySelector('#btnCashflowSavedFilters');
                btn?.click();
            }
            """
        )
        has_modal = await page.evaluate(
            "() => !!document.querySelector('#finModalOverlay') && !!document.querySelector('#finModalOverlay[style*=\"display: flex\"]')"
        )
        if has_modal:
            return
        await page.wait_for_timeout(400)

    await page.wait_for_selector("#finModalOverlay", state="visible", timeout=10000)


async def save_current_filter(page: Page, filter_name: str) -> None:
    if await page.query_selector("#fmCashflowFilterName") is None:
        await open_filters_modal(page)
    await page.evaluate(
        f"() => {{ const el = document.querySelector('#fmCashflowFilterName'); if (el) {{ el.value = {filter_name!r}; el.dispatchEvent(new Event('input')); }} }}"
    )
    await page.evaluate("() => document.querySelector('#btnSaveCashflowFilter')?.click()")
    await page.wait_for_selector(".fin-toast, .toast", timeout=5000)
