"""Tenant-aware rate limiting throttles for Business OS REST API."""

from __future__ import annotations

import logging
from typing import Any

from rest_framework.request import Request
from rest_framework.throttling import SimpleRateThrottle

logger = logging.getLogger(__name__)


class TenantUserRateThrottle(SimpleRateThrottle):
    """Throttles authenticated users scoped by tenant organization."""

    scope = "tenant_user"

    def get_cache_key(self, request: Request, view: Any) -> str | None:
        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            return None

        # Defer API key authenticated requests to ApiKeyRateThrottle
        auth = getattr(request, "auth", None)
        if auth and hasattr(auth, "prefix"):
            return None

        org = getattr(request, "organization", None)
        org_id = getattr(org, "pk", "no_org")
        ident = f"{org_id}:{user.pk}"

        return self.cache_format % {
            "scope": self.scope,
            "ident": ident,
        }


class TenantAnonRateThrottle(SimpleRateThrottle):
    """Throttles anonymous client requests."""

    scope = "tenant_anon"

    def get_cache_key(self, request: Request, view: Any) -> str | None:
        user = getattr(request, "user", None)
        if user and getattr(user, "is_authenticated", False):
            return None

        ident = self.get_ident(request)
        return self.cache_format % {
            "scope": self.scope,
            "ident": ident,
        }


_RESOLVER_REGISTRY: dict[str, Any] = {"plan_rate": None}


def register_plan_rate_resolver(resolver: Any) -> None:
    """Register a resolver callback that returns rate string (e.g. '300/minute') for an organization."""
    _RESOLVER_REGISTRY["plan_rate"] = resolver


def get_organization_rate_limit(org: Any) -> str:
    """Resolve rate limit string for an organization."""
    resolver = _RESOLVER_REGISTRY.get("plan_rate")
    if resolver is not None and org is not None:
        try:
            resolved = resolver(org)
            if resolved:
                return str(resolved)
        except Exception:
            logger.exception("Error resolving plan rate limit for org %s", getattr(org, "pk", org))
    return "60/minute"


class ApiKeyRateThrottle(SimpleRateThrottle):
    """Rate throttle applied to API Key authenticated requests, dynamically adjusted per tenant plan."""

    scope = "api_key"

    def get_rate(self) -> str:
        """Determine rate dynamically based on the tenant's plan tier."""
        org = getattr(self, "_org", None)
        return get_organization_rate_limit(org)

    def get_cache_key(self, request: Request, view: Any) -> str | None:
        auth = getattr(request, "auth", None)
        if not auth or not hasattr(auth, "prefix"):
            return None

        org = getattr(request, "organization", None) or getattr(auth, "organization", None)
        self._org = org

        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)

        return self.cache_format % {
            "scope": self.scope,
            "ident": f"{auth.prefix}:{auth.pk}",
        }
