"""Tests for the Multi-Theme System: Context processor, theme persistence view, and dashboard rendering."""

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import Client, RequestFactory

from apps.accounts.models import User
from apps.core.context_processors import theme_context
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
    assert "Lightweight (Default) • Best for performance" in content


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
