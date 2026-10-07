import pytest
from playwright.sync_api import Page, expect


@pytest.mark.ui
def test_ui_smoke_styleguide(live_server: pytest.FixtureRequest, page: Page) -> None:
    """Verify that the Calm Ledger styleguide renders all components and passes UI smoke checks."""
    server_url = getattr(live_server, "url", str(live_server))
    page.goto(f"{server_url}/_styleguide/")

    # 1. Assert Title & Header
    expect(page).to_have_title("Styleguide & Component Library | Business OS")
    expect(page.locator("h1")).to_contain_text("Calm Ledger Styleguide")

    # 2. Assert Component Sections
    expect(page.locator("#section-colors")).to_be_visible()
    expect(page.locator("#section-typography")).to_be_visible()
    expect(page.locator("#section-buttons")).to_be_visible()
    expect(page.locator("#section-badges")).to_be_visible()
    expect(page.locator("#section-kpis")).to_be_visible()
    expect(page.locator("#section-forms")).to_be_visible()
    expect(page.locator("#section-table")).to_be_visible()
    expect(page.locator("#section-toasts-alerts")).to_be_visible()
    expect(page.locator("#section-empty-state")).to_be_visible()

    # 3. Assert KPI Cards Values & Tabular format
    expect(page.locator("text=$12,480.00")).to_be_visible()
    expect(page.locator("text=$41,920.50")).to_be_visible()

    # 4. Assert Invoices Table renders rows
    table_section = page.locator("#section-table")
    expect(table_section.get_by_text("INV-00231")).to_be_visible()
    expect(table_section.get_by_text("Northwind Ltd")).to_be_visible()
    expect(table_section.get_by_text("Contoso Retail")).to_be_visible()

    # 5. Interactive Toast test
    page.click("#test-trigger-toast-btn")
    toast_locator = page.locator("text=Styleguide notification triggered successfully!")
    expect(toast_locator).to_be_visible()

    # 6. Interactive Modal test (Alpine x-trap & escape/cancel)
    page.click("#test-open-modal-btn")
    modal_title = page.locator("#demo-styleguide-modal-title")
    expect(modal_title).to_be_visible()
    expect(page.locator("text=This modal tests Alpine.js focus trapping")).to_be_visible()

    # Close modal via cancel button
    page.click("#modal-cancel-btn")
    expect(modal_title).not_to_be_visible()

    # 7. Theme toggle test (Light / Dark)
    initial_theme = page.evaluate("() => document.documentElement.getAttribute('data-theme')")
    page.click("#theme-toggle-btn")
    new_theme = page.evaluate("() => document.documentElement.getAttribute('data-theme')")
    assert new_theme != initial_theme
    # Toggle back
    page.click("#theme-toggle-btn")
    restored_theme = page.evaluate("() => document.documentElement.getAttribute('data-theme')")
    assert restored_theme == initial_theme
