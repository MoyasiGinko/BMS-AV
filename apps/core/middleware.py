"""TenantMiddleware resolves the current tenant by subdomain or authenticated user membership fallback."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from django.apps import apps
from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

from apps.core.tenant_context import tenant_context

if TYPE_CHECKING:
    from django.db.models import Model

# Subdomains reserved for infrastructure/public routing
RESERVED_SUBDOMAINS = frozenset({"www", "api", "admin", "app", "mail", "static", "media"})

# Path prefixes that do not require an active tenant
EXEMPT_PREFIXES = (
    "/accounts/",
    "/tenancy/",
    "/admin/",
    "/_styleguide/",
    "/healthz",
    "/readyz",
    "/static/",
    "/media/",
    "/favicon.ico",
)


class TenantMiddleware:
    """Extracts tenant organization from subdomain or user's active membership fallback."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        org = self.resolve_tenant(request)
        request.organization = org  # type: ignore[attr-defined]

        with tenant_context(org):
            # Check if current path requires a tenant and none was found
            if org is None and self.is_tenant_required(request):
                if not getattr(request.user, "is_authenticated", False):
                    return redirect(f"{settings.LOGIN_URL}?next={request.path}")
                # Authenticated user without active org: redirect to org selection or return 404
                if apps.is_installed("apps.tenancy"):
                    return redirect("/tenancy/select/")

            return self.get_response(request)

    def is_tenant_required(self, request: HttpRequest) -> bool:
        """Return True if the requested path requires an active tenant."""
        return all(not request.path.startswith(prefix) for prefix in EXEMPT_PREFIXES)

    def resolve_tenant(self, request: HttpRequest) -> Model | None:
        """Resolve organization by subdomain first, then active user membership fallback."""
        if not apps.is_installed("apps.tenancy"):
            return None

        org_model: Any = apps.get_app_config("tenancy").get_model("Organization")
        if org_model is None:
            return None

        org = self._resolve_from_subdomain(request, org_model)
        if org is not None:
            return org

        return self._resolve_from_user(request, org_model)

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
