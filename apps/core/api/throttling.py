"""Tenant-aware rate limiting throttles for Business OS REST API."""

from __future__ import annotations

from typing import Any

from rest_framework.request import Request
from rest_framework.throttling import SimpleRateThrottle


class TenantUserRateThrottle(SimpleRateThrottle):
    """Throttles authenticated users scoped by tenant organization."""

    scope = "tenant_user"

    def get_cache_key(self, request: Request, view: Any) -> str | None:
        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
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
