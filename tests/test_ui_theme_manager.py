import pytest
from django.contrib.auth import get_user_model
from playwright.sync_api import Page, expect

from apps.tenancy.models import Membership, Organization, Role

User = get_user_model()


@pytest.mark.ui
@pytest.mark.django_db(transaction=True)
def test_ui_theme_manager_and_sidebar_customizer(live_server: pytest.FixtureRequest, page: Page) -> None:
    """Verify that Theme Manager renders presets, sidebar customizer, and styleguide tabs properly."""
    org = Organization.objects.create(name="Theme Manager Corp", slug="theme-manager-corp")
    role = Role.objects.create(organization=org, name="Admin", permissions=["*"])
    user = User.objects.create_user(
        email="thememgr_user@example.com",
        password="ThemeManagerPassword123!",
        name="Theme Manager Tester",
    )
    Membership.objects.create(
        organization=org,
        user=user,
        role=role,
        status=Membership.STATUS_ACTIVE,
    )

    server_url = getattr(live_server, "url", str(live_server))
    page.goto(f"{server_url}/accounts/login/")
    page.fill("#id_login", "thememgr_user@example.com")
    page.fill("#id_password", "ThemeManagerPassword123!")
    page.click("#submit-login-btn")
    page.wait_for_load_state("networkidle")

    # Navigate to Theme Manager
    page.goto(f"{server_url}/settings/theme/")

    # 1. Assert Title and Header
    expect(page.locator("h1")).to_contain_text("Calm Ledger Styleguide & Theme Manager")

    # 2. Assert Navigation Tabs
    expect(page.locator("#tab-btn-presets")).to_be_visible()
    expect(page.locator("#tab-btn-sidebar")).to_be_visible()
    expect(page.locator("#tab-btn-styleguide")).to_be_visible()

    # 3. Assert Presets Tab is Active by default
    expect(page.locator("main").locator("text=Select Active Visual Theme Preset")).to_be_visible()
    expect(page.locator("main").locator("text=Modern & Fast").first).to_be_visible()
    expect(page.locator("main").locator("text=Modern Dark")).to_be_visible()
    expect(page.locator("main").locator("text=Minimal Spatial")).to_be_visible()
    expect(page.get_by_role("main").get_by_text("Neumorphic", exact=True)).to_be_visible()

    # 4. Switch to Sidebar Customizer Tab
    page.click("#tab-btn-sidebar")
    expect(page.locator("text=Sidebar Color Customizer")).to_be_visible()
    expect(page.locator("text=Live Sidebar Preview")).to_be_visible()
    expect(page.locator("#save-sidebar-theme-btn")).to_be_visible()

    # 5. Click a Curated Palette Swatch (e.g. Modern Slate Dark)
    page.click("text=Modern Slate Dark")
    # Verify that the CSS variable was applied in real time to documentElement
    sidebar_bg = page.evaluate("() => document.documentElement.style.getPropertyValue('--sidebar-bg')")
    assert sidebar_bg == "#0f172a"

    # Click Save Sidebar Preferences
    page.click("#save-sidebar-theme-btn")
    expect(page.locator("text=Sidebar appearance saved")).to_be_visible()

    # 6. Switch to Styleguide Tab
    page.click("#tab-btn-styleguide")
    expect(page.locator("#section-colors")).to_be_visible()
    expect(page.locator("#section-buttons")).to_be_visible()
    expect(page.locator("#section-badges")).to_be_visible()
    expect(page.locator("#section-kpis")).to_be_visible()
    expect(page.locator("#section-forms")).to_be_visible()
    expect(page.locator("#section-table")).to_be_visible()
