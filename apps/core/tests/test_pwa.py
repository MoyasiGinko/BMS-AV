"""Unit and integration tests for Progressive Web App (PWA) shell, Service Worker, and Manifest (P6-05)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from django.template.loader import render_to_string
from django.test import RequestFactory

from apps.core import pwa_views


@pytest.fixture
def rf() -> RequestFactory:
    return RequestFactory()


def test_pwa_manifest_default_anonymous(rf: RequestFactory) -> None:
    """Verify default PWA manifest provides required standalone PWA schema and shortcuts."""
    request = rf.get("/manifest.webmanifest")
    response = pwa_views.manifest_view(request)

    assert response.status_code == 200
    assert "application/manifest+json" in response.headers["Content-Type"]
    assert "max-age=3600" in response.headers.get("Cache-Control", "")

    data = json.loads(response.content.decode("utf-8"))
    assert data["name"] == "Business OS - ERP"
    assert data["short_name"] == "Business OS"
    assert data["display"] == "standalone"
    assert data["start_url"] == "/"
    assert data["theme_color"] == "#0f172a"
    assert data["background_color"] == "#0f172a"

    # Validate icon manifests (192, 512, maskable)
    icons = data["icons"]
    assert len(icons) >= 3
    icon_sizes = [icon["sizes"] for icon in icons]
    assert "192x192" in icon_sizes
    assert "512x512" in icon_sizes
    purposes = [icon.get("purpose") for icon in icons]
    assert "maskable" in purposes

    # Validate quick shortcuts (POS, Approvals, Attention, Dashboard)
    shortcuts = data["shortcuts"]
    shortcut_urls = [s["url"] for s in shortcuts]
    assert "/pos/" in shortcut_urls
    assert "/approvals/" in shortcut_urls
    assert "/ai/attention/items/" in shortcut_urls
    assert "/dashboard/" in shortcut_urls


def test_pwa_manifest_tenant_customized(rf: RequestFactory) -> None:
    """Verify manifest customizes name and short_name when tenant organization is active."""
    request = rf.get("/manifest.webmanifest")
    request.organization = SimpleNamespace(name="Apex Retail Global")  # type: ignore[attr-defined]
    response = pwa_views.manifest_view(request)

    assert response.status_code == 200
    data = json.loads(response.content.decode("utf-8"))
    assert data["name"] == "Apex Retail Global - Business OS"
    assert data["short_name"] == "Apex Retail "


def test_pwa_service_worker_headers_and_content(rf: RequestFactory) -> None:
    """Verify Service Worker is served at root scope with Service-Worker-Allowed header
    and correct caching strategy.
    """
    request = rf.get("/service-worker.js")
    response = pwa_views.service_worker_view(request)

    assert response.status_code == 200
    assert "application/javascript" in response.headers["Content-Type"]
    # Critical: Service-Worker-Allowed header permits root scope '/'
    assert response.headers.get("Service-Worker-Allowed") == "/"
    assert "no-cache" in response.headers.get("Cache-Control", "")

    content = response.content.decode("utf-8")
    # Verify pre-cached shell assets
    assert "bos-shell-v1" in content
    assert "'/offline/'" in content
    assert "'/pos/'" in content
    assert "'/approvals/'" in content
    assert "'/static/css/tokens.css'" in content
    assert "'/static/vendor/alpine.min.js'" in content
    assert "'/static/vendor/htmx.min.js'" in content

    # Verify lifecycle and network routing strategies
    assert "self.skipWaiting()" in content
    assert "self.clients.claim()" in content
    assert "request.method !== 'GET'" in content  # Mutations bypass SW cache
    assert "navigate" in content  # Network-first HTML navigations with offline fallback


def test_pwa_offline_view(rf: RequestFactory) -> None:
    """Verify offline fallback view renders Calm Ledger offline shell with network monitor."""
    request = rf.get("/offline/")
    response = pwa_views.offline_view(request)

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "You Are Currently Offline" in content
    assert "Business OS has preserved your static shell" in content
    assert "Retry Connection" in content
    assert "Quick Navigation to Cached Pages" in content
    assert 'href="/pos/"' in content
    assert 'href="/approvals/"' in content


def test_pwa_base_and_app_layout_integration() -> None:
    """Verify base layouts include PWA manifest link, apple meta tags, and SW registration."""
    base_html = render_to_string("layouts/base.html", {"request": None})
    assert '<link rel="manifest" href="/manifest.webmanifest">' in base_html
    assert '<meta name="mobile-web-app-capable" content="yes">' in base_html
    assert '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">' in base_html
    assert "navigator.serviceWorker.register('/service-worker.js'" in base_html
    assert "beforeinstallprompt" in base_html


def test_pos_terminal_mobile_responsive_elements() -> None:
    """Verify POS terminal template includes mobile tab switcher and touch target constraints."""
    terminal_html = render_to_string(
        "pos/terminal.html",
        {
            "shift": SimpleNamespace(
                id=1,
                public_id="00000000-0000-0000-0000-000000000001",
                session_code="S-001",
                cashier=SimpleNamespace(email="cashier@example.com"),
                opened_at=None,
                opening_cash=0,
                status="open",
                terminal_name="Terminal 1",
            ),
            "warehouse": SimpleNamespace(name="Downtown Store"),
            "cart": {"items": [], "subtotal": 0, "tax_amount": 0, "total": 0},
            "products": [],
            "categories": [],
            "branches": [],
            "warehouses": [],
            "payment_methods": [],
            "tax_codes": [],
        },
    )
    # Mobile tab buttons
    assert "mobileTab = 'catalog'" in terminal_html
    assert "mobileTab = 'cart'" in terminal_html
    # Mobile sticky quick checkout bar
    assert "View Cart & Pay" in terminal_html
    # Enlarged touch stepper markers
    assert "min-w-[32px] min-h-[32px]" in terminal_html


def test_approvals_mobile_responsive_elements() -> None:
    """Verify Approvals templates include mobile responsive cards and min 44px touch targets."""
    sample_request = SimpleNamespace(
        pk=1,
        public_id="00000000-0000-0000-0000-000000000002",
        document_reference="PO-2026-001",
        document_type="purchase_order",
        get_document_type_display="Purchase Order",
        status="pending",
        title="Warehouse Supplies",
        amount=250.00,
        requester=SimpleNamespace(email="requester@example.com"),
        created_at=None,
        policy=SimpleNamespace(name="Purchase Over $100"),
        assigned_role=SimpleNamespace(name="Finance Manager"),
        assigned_user=None,
    )
    inbox_html = render_to_string(
        "approvals/partials/inbox_table.html",
        {
            "requests": [sample_request],
            "status_filter": "pending",
        },
    )
    # Both desktop table and mobile card container are defined
    assert "hidden md:block" in inbox_html
    assert "block md:hidden divide-y divide-slate-200 dark:divide-slate-800" in inbox_html
    # 44px minimum touch targets for decision buttons
    assert "min-h-[44px]" in inbox_html
