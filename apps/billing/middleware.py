"""Subscription Read-Only Enforcement Middleware."""

from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse, JsonResponse

from apps.billing.selectors import get_active_subscription

# Safe path prefixes exempt from read-only write restrictions
READ_ONLY_EXEMPT_PREFIXES = (
    "/billing/",
    "/api/v1/billing/",
    "/api/v1/auth/",
    "/accounts/",
    "/admin/",
    "/tenancy/",
    "/healthz",
    "/readyz",
    "/static/",
    "/media/",
    "/favicon.ico",
)


class SubscriptionReadOnlyMiddleware:
    """Enforces read-only mode for organizations with unpaid or expired subscriptions.

    When an organization is in read-only mode (unpaid, canceled, or past_due with expired grace period),
    mutating requests (POST, PUT, PATCH, DELETE) are rejected with HTTP 403 Forbidden,
    allowing access only to billing, tenancy management, and read queries.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        from apps.core.system_mode import is_dedicated_mode

        if is_dedicated_mode():
            return self.get_response(request)

        org = getattr(request, "organization", None)
        if org is None:
            return self.get_response(request)

        # Safe read-only HTTP methods are always allowed
        if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
            return self.get_response(request)

        # Exempt paths (billing settings, authentication, etc.)
        path = request.path
        if any(path.startswith(prefix) for prefix in READ_ONLY_EXEMPT_PREFIXES):
            return self.get_response(request)

        # Check tenant subscription status
        subscription = get_active_subscription(org)
        if subscription and subscription.is_read_only:
            # API requests get a structured JSON 403 response
            if path.startswith("/api/") or request.headers.get("Accept") == "application/json":
                return JsonResponse(
                    {
                        "detail": (
                            "Organization subscription is unpaid or expired. Workspace is in read-only mode."
                        ),
                        "code": "subscription_read_only",
                    },
                    status=403,
                )
            return HttpResponse(
                "Your organization is in read-only mode due to an unpaid or expired subscription. "
                "Please update your subscription in Billing Settings to make changes.",
                status=403,
            )

        return self.get_response(request)
