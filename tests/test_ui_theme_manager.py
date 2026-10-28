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

    # 5. Click Sidebar Preset 1 (Dark Contrast)
    page.click("#sidebar-preset-dark-contrast")
    # Verify that the CSS variable was applied in real time to documentElement
    sidebar_bg = page.evaluate("() => document.documentElement.style.getPropertyValue('--sidebar-bg')")
    assert sidebar_bg == "#0f172a"

    # Select Custom Mode to enable the Save button and verify saving custom palette
    page.click("#sidebar-preset-custom")
    expect(page.locator("#save-sidebar-theme-btn")).to_be_enabled()
    page.click("#save-sidebar-theme-btn")
    expect(page.locator("text=Sidebar appearance saved").first).to_be_visible()

    # 6. Switch to Styleguide Tab
    page.click("#tab-btn-styleguide")
    expect(page.locator("#section-colors")).to_be_visible()
    expect(page.locator("#section-buttons")).to_be_visible()
    expect(page.locator("#section-badges")).to_be_visible()
    expect(page.locator("#section-kpis")).to_be_visible()
    expect(page.locator("#section-forms")).to_be_visible()
    expect(page.locator("#section-table")).to_be_visible()


@pytest.mark.ui
@pytest.mark.django_db(transaction=True)
def test_ui_per_theme_sidebar_preset_persistence(live_server: pytest.FixtureRequest, page: Page) -> None:
    """Verify that each theme preset has 3 sidebar presets (Dark Contrast default, Light, Custom)
    and that switching themes restores the previously chosen sidebar preset for that theme.
    """
    org = Organization.objects.create(name="Theme Sticky Corp", slug="theme-sticky-corp")
    role = Role.objects.create(organization=org, name="Admin", permissions=["*"])
    user = User.objects.create_user(
        email="themesticky_user@example.com",
        password="ThemeManagerPassword123!",
        name="Theme Sticky Tester",
    )
    Membership.objects.create(
        organization=org,
        user=user,
        role=role,
        status=Membership.STATUS_ACTIVE,
    )

    server_url = getattr(live_server, "url", str(live_server))
    page.goto(f"{server_url}/accounts/login/")
    page.fill("#id_login", "themesticky_user@example.com")
    page.fill("#id_password", "ThemeManagerPassword123!")
    page.click("#submit-login-btn")
    page.wait_for_load_state("networkidle")

    page.goto(f"{server_url}/settings/theme/#sidebar")

    # 1. On 'fast' (default), verify 3 sidebar presets are visible
    expect(page.locator("#sidebar-preset-dark-contrast")).to_be_visible()
    expect(page.locator("#sidebar-preset-light")).to_be_visible()
    expect(page.locator("#sidebar-preset-custom")).to_be_visible()

    # 2. Switch active theme to 'spatial' using the quick switcher
    page.click("button:has-text('Spatial Mode')")
    expect(page.locator("html")).to_have_attribute("data-theme", "spatial")

    # 3. For 'spatial', select 'Light Mode' sidebar preset
    page.click("#sidebar-preset-light")
    # Verify the light background for spatial is applied
    bg_spatial_light = page.evaluate("() => document.documentElement.style.getPropertyValue('--sidebar-bg')")
    assert "255, 255, 255" in bg_spatial_light

    # 4. Switch theme to 'Fast Mode'
    page.click("button:has-text('Fast Mode')")
    expect(page.locator("html")).to_have_attribute("data-theme", "fast")
    # Fast should still have its default 'dark_contrast' preset
    bg_fast = page.evaluate("() => document.documentElement.style.getPropertyValue('--sidebar-bg')")
    assert bg_fast == "#0f172a"

    # 5. Switch back to 'Spatial Mode'
    page.click("button:has-text('Spatial Mode')")
    expect(page.locator("html")).to_have_attribute("data-theme", "spatial")
    # Spatial should have automatically restored its previously selected 'Light Mode' preset!
    bg_spatial_restored = page.evaluate(
        "() => document.documentElement.style.getPropertyValue('--sidebar-bg')"
    )
    assert "255, 255, 255" in bg_spatial_restored

    # 6. Switch to 'Neumorphic Mode' and verify default Light bg and Dark preset
    page.click("button:has-text('Neumorphic Mode')")
    expect(page.locator("html")).to_have_attribute("data-theme", "neumorphic")
    # Default for neumorphic is Soft Clay Light (#e2e8f0)
    bg_neu_default = page.evaluate("() => document.documentElement.style.getPropertyValue('--sidebar-bg')")
    assert bg_neu_default == "#e2e8f0"
    # Select dark preset for neumorphic
    page.click("#sidebar-preset-dark-contrast")
    bg_neu_dark = page.evaluate("() => document.documentElement.style.getPropertyValue('--sidebar-bg')")
    assert bg_neu_dark == "#1e293b"


@pytest.mark.ui
@pytest.mark.django_db(transaction=True)
def test_ui_sidebar_presets_locked_and_custom_editable(
    live_server: pytest.FixtureRequest, page: Page
) -> None:
    """Verify that Preset 1 and Preset 2 cannot be edited (inputs disabled)
    and only Custom mode allows editing and saving, across all themes.
    """
    org = Organization.objects.create(name="Theme Lock Corp", slug="theme-lock-corp")
    role = Role.objects.create(organization=org, name="Admin", permissions=["*"])
    user = User.objects.create_user(
        email="themelock_user@example.com",
        password="ThemeManagerPassword123!",
        name="Theme Lock Tester",
    )
    Membership.objects.create(
        organization=org,
        user=user,
        role=role,
        status=Membership.STATUS_ACTIVE,
    )

    server_url = getattr(live_server, "url", str(live_server))
    page.goto(f"{server_url}/accounts/login/")
    page.fill("#id_login", "themelock_user@example.com")
    page.fill("#id_password", "ThemeManagerPassword123!")
    page.click("#submit-login-btn")
    page.wait_for_load_state("networkidle")

    page.goto(f"{server_url}/settings/theme/#sidebar")

    # 1. By default on 'fast' theme, Preset 1 ('dark_contrast') is active
    expect(page.locator("text=Preset Colors are Locked (Read-Only)")).to_be_visible()
    first_color_picker = page.locator('input[type="color"]').first
    first_text_input = page.locator('input[placeholder="#ffffff"]').first
    save_btn = page.locator("#save-sidebar-theme-btn")

    # Both inputs and save button must be disabled when in Preset 1
    expect(first_color_picker).to_be_disabled()
    expect(first_text_input).to_be_disabled()
    expect(save_btn).to_be_disabled()

    # Verify Preset 1 background applied
    bg_fast_p1 = page.evaluate("() => document.documentElement.style.getPropertyValue('--sidebar-bg')")
    assert bg_fast_p1 == "#0f172a"

    # 2. Select Preset 2 ('light')
    page.click("#sidebar-preset-light")
    # Inputs and save button must remain disabled
    expect(page.locator("text=Preset Colors are Locked (Read-Only)")).to_be_visible()
    expect(first_color_picker).to_be_disabled()
    expect(first_text_input).to_be_disabled()
    expect(save_btn).to_be_disabled()

    # Verify Preset 2 color applied
    bg_fast_p2 = page.evaluate("() => document.documentElement.style.getPropertyValue('--sidebar-bg')")
    assert bg_fast_p2 == "#ffffff"

    # 3. Select Custom Mode
    page.click("#sidebar-preset-custom")
    expect(page.locator("text=Custom Palette Active & Unlocked")).to_be_visible()
    # Now inputs and save button must be enabled
    expect(first_color_picker).to_be_enabled()
    expect(first_text_input).to_be_enabled()
    expect(save_btn).to_be_enabled()

    # 4. Switch theme to 'neumorphic'
    page.click("button:has-text('Neumorphic Mode')")
    expect(page.locator("html")).to_have_attribute("data-theme", "neumorphic")

    # In neumorphic, Preset 1 (Soft Clay Light) should be active by default and inputs locked
    expect(page.locator("text=Preset Colors are Locked (Read-Only)")).to_be_visible()
    expect(first_color_picker).to_be_disabled()
    bg_neu_p1 = page.evaluate("() => document.documentElement.style.getPropertyValue('--sidebar-bg')")
    assert bg_neu_p1 == "#e2e8f0"

    # Select Dark Preset for neumorphic
    page.click("#sidebar-preset-dark-contrast")
    expect(first_color_picker).to_be_disabled()
    bg_neu_dark = page.evaluate("() => document.documentElement.style.getPropertyValue('--sidebar-bg')")
    assert bg_neu_dark == "#1e293b"

    # Unlock custom for neumorphic via "Unlock & Edit in Custom" button
    page.click("#unlock-custom-sidebar-btn")
    expect(page.locator("text=Custom Palette Active & Unlocked")).to_be_visible()
    expect(first_color_picker).to_be_enabled()
    expect(save_btn).to_be_enabled()


@pytest.mark.ui
@pytest.mark.django_db(transaction=True)
def test_ui_neumorphic_sidebar_preset_dark_bg_retention(
    live_server: pytest.FixtureRequest, page: Page
) -> None:
    """Verify that selecting dark preset in neumorphic mode properly applies and retains dark bg colors."""
    org = Organization.objects.create(name="Neu Org", slug="neu-org")
    role = Role.objects.create(organization=org, name="Admin", permissions=["*"])
    user = User.objects.create_user(
        email="neu_tester@example.com",
        password="NeuPassword123!",
        name="Neu Tester",
    )
    Membership.objects.create(
        organization=org,
        user=user,
        role=role,
        status=Membership.STATUS_ACTIVE,
    )

    server_url = getattr(live_server, "url", str(live_server))
    page.goto(f"{server_url}/accounts/login/")
    page.fill("#id_login", "neu_tester@example.com")
    page.fill("#id_password", "NeuPassword123!")
    page.click("#submit-login-btn")
    page.wait_for_load_state("networkidle")

    # Navigate to Sidebar Studio
    page.goto(f"{server_url}/settings/theme/#sidebar")
    page.wait_for_selector("#sidebar-preset-dark-contrast")

    # Switch to Neumorphic mode
    page.click("button:has-text('Neumorphic Mode')")
    expect(page.locator("html")).to_have_attribute("data-theme", "neumorphic")

    # 1. Preset 1 (Soft Clay Light) is default: check preview box and aside bg
    page.click("#sidebar-preset-light")
    page.wait_for_timeout(200)
    aside_bg_light = page.evaluate(
        "() => getComputedStyle(document.querySelector('aside.bos-sidebar')).backgroundColor"
    )
    mock_bg_light = page.evaluate(
        "() => getComputedStyle(document.querySelector('#sidebar-live-preview-box')).backgroundColor"
    )
    assert aside_bg_light == "rgb(226, 232, 240)"
    assert mock_bg_light == "rgb(226, 232, 240)"

    # 2. Select Preset 2 (Tactile Slate Dark)
    page.click("#sidebar-preset-dark-contrast")
    page.wait_for_timeout(200)
    aside_bg_dark = page.evaluate(
        "() => getComputedStyle(document.querySelector('aside.bos-sidebar')).backgroundColor"
    )
    mock_bg_dark = page.evaluate(
        "() => getComputedStyle(document.querySelector('#sidebar-live-preview-box')).backgroundColor"
    )
    assert aside_bg_dark == "rgb(30, 41, 59)"
    assert mock_bg_dark == "rgb(30, 41, 59)"

    # 3. Reload page and verify dark background is retained (does NOT revert to white)
    page.reload()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(200)
    aside_bg_reloaded = page.evaluate(
        "() => getComputedStyle(document.querySelector('aside.bos-sidebar')).backgroundColor"
    )
    mock_bg_reloaded = page.evaluate(
        "() => getComputedStyle(document.querySelector('#sidebar-live-preview-box')).backgroundColor"
    )
    assert aside_bg_reloaded == "rgb(30, 41, 59)"
    assert mock_bg_reloaded == "rgb(30, 41, 59)"

    # 4. Switch around tabs and verify dark background remains
    page.click("#tab-btn-presets")
    page.wait_for_timeout(150)
    aside_bg_presets = page.evaluate(
        "() => getComputedStyle(document.querySelector('aside.bos-sidebar')).backgroundColor"
    )
    assert aside_bg_presets == "rgb(30, 41, 59)"

    page.click("#tab-btn-sidebar")
    page.wait_for_timeout(150)
    aside_bg_sidebar_tab = page.evaluate(
        "() => getComputedStyle(document.querySelector('aside.bos-sidebar')).backgroundColor"
    )
    mock_bg_sidebar_tab = page.evaluate(
        "() => getComputedStyle(document.querySelector('#sidebar-live-preview-box')).backgroundColor"
    )
    assert aside_bg_sidebar_tab == "rgb(30, 41, 59)"
    assert mock_bg_sidebar_tab == "rgb(30, 41, 59)"
