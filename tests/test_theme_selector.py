"""Tests for the Multi-Theme System: Context processor, theme persistence view, and dashboard rendering."""

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import Client, RequestFactory

from apps.accounts.models import User
from apps.core.context_processors import ALLOWED_THEMES, THEME_SIDEBAR_PRESETS, theme_context
from apps.tenancy.models import Membership, Organization, Role


@pytest.fixture
def theme_test_env(db: None) -> dict[str, object]:
    org = Organization.objects.create(name="Theme Org", slug="theme-org")
    role = Role.objects.create(
        organization=org,
        name="Admin",
        permissions=["*"],
    )
    user = User.objects.create_user(
        email="theme_user@example.com",
        password="password123",
        name="Theme Tester",
        theme="fast",
    )
    Membership.objects.create(
        organization=org,
        user=user,
        role=role,
        status="active",
    )
    return {"org": org, "user": user, "role": role}


@pytest.mark.django_db
def test_theme_context_processor_defaults_to_fast() -> None:
    rf = RequestFactory()
    req = rf.get("/")
    req.user = AnonymousUser()
    ctx = theme_context(req)
    assert ctx["current_theme"] == "fast"
    assert len(ctx["available_themes"]) == 4
    theme_ids = [t["id"] for t in ctx["available_themes"]]
    assert theme_ids == ["fast", "dark", "spatial", "neumorphic"]


@pytest.mark.django_db
def test_theme_context_processor_reads_cookie() -> None:
    rf = RequestFactory()
    req = rf.get("/")
    req.user = AnonymousUser()
    req.COOKIES["bos_theme"] = "neumorphic"
    ctx = theme_context(req)
    assert ctx["current_theme"] == "neumorphic"


@pytest.mark.django_db
def test_theme_context_processor_reads_user_profile(theme_test_env: dict[str, object]) -> None:
    user: User = theme_test_env["user"]  # type: ignore[assignment]
    user.theme = "spatial"
    user.save()

    rf = RequestFactory()
    req = rf.get("/")
    req.user = user
    ctx = theme_context(req)
    assert ctx["current_theme"] == "spatial"


@pytest.mark.django_db
def test_set_theme_view_authenticated(theme_test_env: dict[str, object]) -> None:
    user: User = theme_test_env["user"]  # type: ignore[assignment]
    client = Client()
    client.force_login(user)

    # Post new theme
    resp = client.post(
        "/settings/theme/",
        data='{"theme": "neumorphic"}',
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["theme"] == "neumorphic"

    # User profile updated
    user.refresh_from_db()
    assert user.theme == "neumorphic"

    # Cookie set
    assert "bos_theme" in resp.cookies
    assert resp.cookies["bos_theme"].value == "neumorphic"


@pytest.mark.django_db
def test_set_theme_view_rejects_invalid_theme(theme_test_env: dict[str, object]) -> None:
    client = Client()
    resp = client.post(
        "/settings/theme/",
        data='{"theme": "hacker-green"}',
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert "Invalid theme" in resp.json()["error"]


@pytest.mark.django_db
def test_dashboard_renders_theme_and_selector(theme_test_env: dict[str, object]) -> None:
    user: User = theme_test_env["user"]  # type: ignore[assignment]
    user.theme = "neumorphic"
    user.save()

    client = Client()
    client.force_login(user)

    resp = client.get("/")
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")

    # Server renders data-theme="neumorphic"
    assert 'data-theme="neumorphic"' in content
    # Renders the 4 theme options
    assert "Modern &amp; Fast" in content or "Modern & Fast" in content
    assert "Modern Dark" in content
    assert "Minimal Spatial" in content
    assert "Clean, high-contrast" in content or "Lightweight" in content


@pytest.mark.django_db
def test_dashboard_default_theme_is_checked(theme_test_env: dict[str, object]) -> None:
    user: User = theme_test_env["user"]  # type: ignore[assignment]
    user.theme = "fast"
    user.save()

    client = Client()
    client.force_login(user)

    resp = client.get("/")
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")

    assert 'data-theme="fast"' in content
    # Ensure value="fast" input has checked attribute
    assert 'value="fast"' in content
    assert "checked" in content


@pytest.mark.django_db
def test_theme_manager_view_renders_tabs_and_controls(theme_test_env: dict[str, object]) -> None:
    user: User = theme_test_env["user"]  # type: ignore[assignment]
    client = Client()
    client.force_login(user)

    resp = client.get("/settings/theme/")
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")

    # Assert tabs exist
    assert "Theme Presets" in content
    assert "Sidebar Customizer" in content
    assert "Styleguide &amp; Components" in content or "Styleguide & Components" in content

    # Assert all 4 theme preset options are present
    assert "Modern &amp; Fast" in content or "Modern & Fast" in content
    assert "Modern Dark" in content
    assert "Minimal Spatial" in content
    assert "Neumorphic" in content

    # Assert sidebar customization controls exist
    assert "Sidebar Background Color" in content
    assert "Sidebar Text &amp; Icon Color" in content or "Sidebar Text & Icon Color" in content
    assert "Hover Background Color" in content
    assert "Hover Text Color" in content
    assert "Active Background Color" in content
    assert "Active Text &amp; Border Color" in content or "Active Text & Border Color" in content
    assert "Live Sidebar Preview" in content


@pytest.mark.django_db
def test_set_theme_view_sidebar_customization(theme_test_env: dict[str, object]) -> None:
    user: User = theme_test_env["user"]  # type: ignore[assignment]
    client = Client()
    client.force_login(user)

    payload = {
        "sidebar": {
            "bg": "#0f172a",
            "text": "#94a3b8",
            "hover_bg": "#1e293b",
            "hover_text": "#f8fafc",
            "active_bg": "#14b8a6",
            "active_text": "#ffffff",
        }
    }

    resp = client.post(
        "/settings/theme/",
        data=payload,
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["sidebar"]["bg"] == "#0f172a"
    assert data["sidebar"]["active_bg"] == "#14b8a6"

    # User profile updated
    user.refresh_from_db()
    assert user.theme_config["sidebar"]["bg"] == "#0f172a"
    assert user.theme_config["sidebar"]["text"] == "#94a3b8"

    # Cookie set
    assert "bos_sidebar_theme" in resp.cookies


@pytest.mark.django_db
def test_set_theme_view_reset_sidebar(theme_test_env: dict[str, object]) -> None:
    user: User = theme_test_env["user"]  # type: ignore[assignment]
    user.theme_config = {"sidebar": {"bg": "#0f172a"}}
    user.save()

    client = Client()
    client.force_login(user)

    resp = client.post(
        "/settings/theme/",
        data={"reset_sidebar": True},
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data.get("sidebar_reset") is True

    # User profile updated: sidebar removed from theme_config
    user.refresh_from_db()
    assert "sidebar" not in user.theme_config


@pytest.mark.django_db
def test_theme_context_processor_with_custom_sidebar(theme_test_env: dict[str, object]) -> None:
    user: User = theme_test_env["user"]  # type: ignore[assignment]
    user.theme_config = {
        "sidebar": {
            "bg": "#1e1b4b",
            "text": "#c7d2fe",
            "hover_bg": "#312e81",
            "hover_text": "#ffffff",
            "active_bg": "#6366f1",
            "active_text": "#ffffff",
        }
    }
    user.save()

    rf = RequestFactory()
    req = rf.get("/")
    req.user = user

    ctx = theme_context(req)
    assert ctx["custom_sidebar"]["bg"] == "#1e1b4b"
    assert ctx["active_sidebar_colors"]["bg"] == "#1e1b4b"
    assert ctx["active_sidebar_colors"]["active_bg"] == "#6366f1"


@pytest.mark.django_db
def test_per_theme_sidebar_preset_persistence(theme_test_env: dict[str, object]) -> None:
    user: User = theme_test_env["user"]  # type: ignore[assignment]
    client = Client()
    client.force_login(user)

    # 1. Set sidebar preset for 'spatial' to 'light'
    resp = client.post(
        "/settings/theme/",
        data={
            "theme": "spatial",
            "target_theme": "spatial",
            "sidebar_mode": "light",
        },
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["sidebar_mode"] == "light"
    assert resp.json()["sidebar"]["bg"] == "rgba(255, 255, 255, 0.90)"

    # 2. Switch back to 'fast' without specifying mode: defaults to 'dark_contrast'
    resp = client.post(
        "/settings/theme/",
        data={"theme": "fast"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["sidebar_mode"] == "dark_contrast"
    assert resp.json()["sidebar"]["bg"] == "#0f172a"

    # 3. Switch back to 'spatial': should recall previously selected 'light' mode!
    resp = client.post(
        "/settings/theme/",
        data={"theme": "spatial"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["sidebar_mode"] == "light"
    assert resp.json()["sidebar"]["bg"] == "rgba(255, 255, 255, 0.90)"


@pytest.mark.django_db
def test_custom_sidebar_per_theme_isolation(theme_test_env: dict[str, object]) -> None:
    user: User = theme_test_env["user"]  # type: ignore[assignment]
    client = Client()
    client.force_login(user)

    # Set custom colors for 'fast'
    resp = client.post(
        "/settings/theme/",
        data={
            "target_theme": "fast",
            "sidebar_mode": "custom",
            "sidebar": {"bg": "#111111", "text": "#aaaaaa"},
        },
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["sidebar"]["bg"] == "#111111"

    # Set custom colors for 'dark'
    resp = client.post(
        "/settings/theme/",
        data={
            "target_theme": "dark",
            "sidebar_mode": "custom",
            "sidebar": {"bg": "#222222", "text": "#bbbbbb"},
        },
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["sidebar"]["bg"] == "#222222"

    user.refresh_from_db()
    assert user.theme_config["sidebar_custom"]["fast"]["bg"] == "#111111"
    assert user.theme_config["sidebar_custom"]["dark"]["bg"] == "#222222"


def test_two_presets_and_one_custom_per_theme_schema() -> None:
    """Verify that every theme has exactly two presets of sidebar theme and supports 1 custom."""
    required_keys = {"bg", "text", "hover_bg", "hover_text", "active_bg", "active_text", "name"}

    for theme in ALLOWED_THEMES:
        assert theme in THEME_SIDEBAR_PRESETS, f"Theme {theme} missing in THEME_SIDEBAR_PRESETS"
        presets = THEME_SIDEBAR_PRESETS[theme]

        # Each theme must have exactly two curated presets
        preset_modes = set(presets.keys())
        msg = (
            f"Theme {theme} must have exactly two sidebar presets: "
            f"'dark_contrast' (Preset 1) and 'light' (Preset 2). Found: {preset_modes}"
        )
        assert preset_modes == {"dark_contrast", "light"}, msg

        for mode_key, colors in presets.items():
            missing = required_keys - set(colors.keys())
            assert not missing, f"Theme {theme} preset {mode_key} is missing keys: {missing}"
            assert colors["bg"].startswith("#") or colors["bg"].startswith("rgba(")
            assert colors["text"].startswith("#") or colors["text"].startswith("rgba(")
            assert colors["hover_bg"].startswith("#") or colors["hover_bg"].startswith("rgba(")
            assert colors["hover_text"].startswith("#") or colors["hover_text"].startswith("rgba(")
            assert colors["active_bg"].startswith("#") or colors["active_bg"].startswith("rgba(")
            assert colors["active_text"].startswith("#") or colors["active_text"].startswith("rgba(")


@pytest.mark.django_db
def test_theme_manager_template_locks_preset_inputs_and_exposes_custom(
    theme_test_env: dict[str, object],
) -> None:
    """Verify Theme Manager template locks Presets 1 & 2 while Custom mode is editable."""
    user: User = theme_test_env["user"]  # type: ignore[assignment]
    client = Client()
    client.force_login(user)

    resp = client.get("/settings/theme/#sidebar")
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")

    # Assert Preset 1, Preset 2, and Custom cards are present
    assert 'id="sidebar-preset-dark-contrast"' in content
    assert 'id="sidebar-preset-light"' in content
    assert 'id="sidebar-preset-custom"' in content

    # Assert locked banners and disabled input bindings exist
    assert ':disabled="getActiveMode() !== \'custom\'"' in content
    assert "Preset Colors are Locked (Read-Only)" in content
    assert "Unlock &amp; Edit in Custom" in content or "Unlock & Edit in Custom" in content
    assert "Custom Palette Active &amp; Unlocked" in content or "Custom Palette Active & Unlocked" in content
    assert "3. Custom Palette" in content


def test_neumorphic_sidebar_presets_light_default_and_dark() -> None:
    """Verify that neumorphic mode has soft clay light as default and preserves surface continuity."""
    presets = THEME_SIDEBAR_PRESETS["neumorphic"]
    assert "light" in presets
    assert presets["light"]["name"] == "Soft Clay Light (Default)"
    assert presets["light"]["bg"] == "#E6E9F2"
