"""Tenant, Request ID, and Security Headers middleware for Business OS.

- RequestIdMiddleware: Assigns or propagates X-Request-ID on request and response and sets contextvar.
- TenantMiddleware: Resolves tenant by header (API), subdomain, or active user membership fallback.
- SecurityHeadersMiddleware: Inforces modern HTTP security headers (Permissions-Policy, etc.).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from django.apps import apps
from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect

from apps.core.permissions import get_user_allowed_branch_ids
from apps.core.system_mode import (
    get_primary_organization,
    is_dedicated_mode,
    is_system_initialized,
)
from apps.core.tenant_context import (
    set_current_request_id,
    set_current_user_id,
    tenant_context,
)

if TYPE_CHECKING:
    from django.db.models import Model

# Subdomains reserved for infrastructure/public routing
RESERVED_SUBDOMAINS = frozenset({"www", "api", "admin", "app", "mail", "static", "media"})

# Path prefixes that do not require an active tenant (no redirect)
EXEMPT_PREFIXES = (
    "/setup/",
    "/api/",
    "/accounts/",
    "/tenancy/",
    "/admin/",
    "/backoffice/",
    "/theme-manager/",
    "/healthz",
    "/readyz",
    "/static/",
    "/media/",
    "/favicon.ico",
    "/settings/theme/",
)



SETUP_EXEMPT_PREFIXES = (
    "/setup/",
    "/static/",
    "/media/",
    "/healthz",
    "/readyz",
    "/favicon.ico",
)

class RequestIdMiddleware:
    """Ensures each request has an X-Request-ID assigned and attached to response headers."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        req_id = request.headers.get("X-Request-ID") or request.META.get("HTTP_X_REQUEST_ID")
        if not req_id:
            try:
                req_id = str(uuid.uuid7())
            except AttributeError:
                req_id = str(uuid.uuid4())

        request.request_id = req_id  # type: ignore[attr-defined]
        request.id = req_id  # type: ignore[attr-defined]
        set_current_request_id(req_id)

        try:
            response = self.get_response(request)
        finally:
            set_current_request_id(None)

        response["X-Request-ID"] = req_id
        return response


class SecurityHeadersMiddleware:
    """Attaches standard security headers: Permissions-Policy, Referrer-Policy, nosniff."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        response.setdefault(
            "Permissions-Policy",
            (
                "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
                "magnetometer=(), microphone=(), payment=(), usb=()"
            ),
        )
        response.setdefault("X-Content-Type-Options", "nosniff")
        response.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response


class TenantMiddleware:
    """Extracts tenant organization from header, subdomain, or user's active membership fallback."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not is_system_initialized() and not any(
            request.path.startswith(prefix) for prefix in SETUP_EXEMPT_PREFIXES
        ):
            if request.path.startswith("/api/"):
                return JsonResponse(
                    {"error": "system_not_initialized", "message": "System setup is required at /setup/."},
                    status=503,
                )
            return redirect("/setup/")

        org = self.resolve_tenant(request)
        request.organization = org  # type: ignore[attr-defined]
        request.tenant = org  # type: ignore[attr-defined]
        request.branch = self.resolve_branch(request, org)  # type: ignore[attr-defined]

        user = getattr(request, "user", None)
        user_id = getattr(user, "pk", None) if getattr(user, "is_authenticated", False) else None
        set_current_user_id(user_id)

        try:
            with tenant_context(org):
                # Check if current path requires a tenant and none was found
                if org is None and self.is_tenant_required(request):
                    if not getattr(request.user, "is_authenticated", False):
                        return redirect(f"{settings.LOGIN_URL}?next={request.path}")
                    # Authenticated user without active org: redirect to org selection
                    if apps.is_installed("apps.tenancy"):
                        return redirect("/tenancy/select/")

                return self.get_response(request)
        finally:
            set_current_user_id(None)

    def resolve_branch(self, request: HttpRequest, org: Model | None) -> Model | None:
        """Resolve active branch from session for current organization and user."""
        if org is None or not apps.is_installed("apps.tenancy"):
            return None

        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            return None

        session = getattr(request, "session", None)
        active_branch_id = session.get("active_branch_id") if session else None

        branch_model: Any = apps.get_app_config("tenancy").get_model("Branch")
        if branch_model is None:
            return None

        allowed_ids = get_user_allowed_branch_ids(user, organization=org)

        if active_branch_id:
            branch = branch_model.all_tenants.filter(
                organization=org, pk=active_branch_id, is_active=True
            ).first()
            if branch and (allowed_ids is None or branch.pk in allowed_ids):
                return branch
            if session:
                session["active_branch_id"] = None

        if allowed_ids and len(allowed_ids) == 1:
            single_branch = branch_model.all_tenants.filter(
                organization=org, pk=allowed_ids[0], is_active=True
            ).first()
            if single_branch:
                return single_branch

        return None

    def is_tenant_required(self, request: HttpRequest) -> bool:
        """Return True if the requested path requires an active tenant."""
        return all(not request.path.startswith(prefix) for prefix in EXEMPT_PREFIXES)

    def resolve_tenant(self, request: HttpRequest) -> Model | None:
        """Resolve organization by header first, then subdomain, then active user membership fallback."""
        if not apps.is_installed("apps.tenancy"):
            return None

        # In dedicated mode, auto-bind the primary organization
        if is_dedicated_mode():
            primary_org = get_primary_organization()
            if primary_org is not None:
                return primary_org

        org_model: Any = apps.get_app_config("tenancy").get_model("Organization")
        if org_model is None:
            return None

        # 1. Header (essential for API clients: X-Organization-ID or X-Tenant-ID)
        org = self._resolve_from_header(request, org_model)
        if org is not None:
            return org

        # 2. Subdomain
        org = self._resolve_from_subdomain(request, org_model)
        if org is not None:
            return org

        # 3. User membership / active session
        return self._resolve_from_user(request, org_model)

    def _resolve_from_header(self, request: HttpRequest, org_model: Any) -> Model | None:
        header_val = (
            request.headers.get("X-Organization-ID")
            or request.headers.get("X-Tenant-ID")
            or request.META.get("HTTP_X_ORGANIZATION_ID")
            or request.META.get("HTTP_X_TENANT_ID")
        )
        if not header_val:
            return None

        val = str(header_val).strip()
        try:
            parsed_uuid = uuid.UUID(val)
            return org_model.objects.filter(public_id=parsed_uuid, is_active=True).first()
        except ValueError:
            pass

        if val.isdigit():
            return org_model.objects.filter(id=int(val), is_active=True).first()

        return org_model.objects.filter(slug=val, is_active=True).first()

    def _resolve_from_subdomain(self, request: HttpRequest, org_model: Any) -> Model | None:
        subdomain = self._extract_subdomain(request)
        if subdomain and subdomain not in RESERVED_SUBDOMAINS:
            return org_model.objects.filter(slug=subdomain, is_active=True).first()
        return None

    def _resolve_from_user(self, request: HttpRequest, org_model: Any) -> Model | None:
        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            return None

        session = getattr(request, "session", None)
        if session:
            session_org_id = session.get("active_org_id")
            if session_org_id:
                org = org_model.objects.filter(id=session_org_id, is_active=True).first()
                if org:
                    return org

        try:
            membership_model: Any = apps.get_app_config("tenancy").get_model("Membership")
            if membership_model:
                membership = (
                    membership_model.all_tenants.filter(user=user, organization__is_active=True)
                    .select_related("organization")
                    .first()
                )
                if membership and membership.organization:
                    if session:
                        session["active_org_id"] = membership.organization.id
                    return membership.organization
        except LookupError, AttributeError:
            pass

        return None

    def _extract_subdomain(self, request: HttpRequest) -> str | None:
        """Extract subdomain from HTTP host."""
        host = request.get_host().split(":")[0].lower()
        base_domain = getattr(settings, "BASE_DOMAIN", "localhost").lower()

        # e.g., acme.localhost -> acme
        if host.endswith(f".{base_domain}"):
            sub = host[: -len(f".{base_domain}")]
            if "." not in sub:
                return sub
        return None
