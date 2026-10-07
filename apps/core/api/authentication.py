"""DRF authentication backend for scoped, hashed API keys."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from django.http import HttpRequest
from django.utils import timezone
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework import authentication
from rest_framework.exceptions import AuthenticationFailed

from apps.core.models import ApiKey
from apps.core.selectors import get_active_api_key_by_prefix
from apps.core.services import is_ip_allowed, record_api_key_usage
from apps.core.tenant_context import set_current_organization


def _get_client_ip(request: HttpRequest) -> str:
    """Extract client IP from request headers or remote address."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return str(request.META.get("REMOTE_ADDR", "")).strip()


class ApiKeyPrincipal:
    """Lightweight principal representation for API key clients without a linked User."""

    is_active = True
    is_authenticated = True
    is_anonymous = False
    is_staff = False
    is_superuser = False

    def __init__(self, api_key: ApiKey) -> None:
        self.api_key = api_key
        self.pk = None
        self.email = f"apikey+{api_key.prefix}@{api_key.organization.slug}.local"
        self.name = f"API Key ({api_key.name})"

    def __str__(self) -> str:
        return self.name


def _extract_raw_key(request: HttpRequest) -> str | None:
    """Extract raw API key token from request headers if present."""
    x_api_key = request.headers.get("X-API-Key") or request.META.get("HTTP_X_API_KEY")
    if x_api_key:
        return str(x_api_key).strip()

    auth_header = request.headers.get("Authorization") or request.META.get("HTTP_AUTHORIZATION")
    if not auth_header:
        return None

    parts = str(auth_header).split()
    if len(parts) != 2:
        return None

    auth_type, auth_token = parts[0].lower(), parts[1].strip()
    is_api_key = auth_type == "api-key"
    is_bearer = auth_type == "bearer" and auth_token.startswith("bos_live_")
    if is_api_key or is_bearer:
        return auth_token
    return None


class ApiKeyAuthentication(authentication.BaseAuthentication):
    """Authenticates API requests via X-API-Key header or Authorization: Api-Key <token>."""

    def authenticate_header(self, request: HttpRequest) -> str:
        return 'Api-Key realm="api"'

    def authenticate(self, request: HttpRequest) -> tuple[Any, ApiKey] | None:
        raw_key = _extract_raw_key(request)
        if not raw_key:
            return None

        # 3. Validate format: bos_live_<prefix_slug>_<secret_slug>
        if not raw_key.startswith("bos_live_"):
            raise AuthenticationFailed("Invalid API key format.")

        parts = raw_key.split("_")
        if len(parts) != 4:
            raise AuthenticationFailed("Invalid API key format.")

        prefix = f"{parts[0]}_{parts[1]}_{parts[2]}"

        # 4. Lookup active API key
        api_key = get_active_api_key_by_prefix(prefix=prefix)
        if not api_key:
            raise AuthenticationFailed("Invalid or revoked API key.")

        # 5. Constant-time hash verification
        computed_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(api_key.key_hash, computed_hash):
            raise AuthenticationFailed("Invalid API key.")

        # 6. Check expiration
        if api_key.expires_at is not None and timezone.now() > api_key.expires_at:
            raise AuthenticationFailed("API key has expired.")

        # 7. Check IP allowlist
        client_ip = _get_client_ip(request)
        if not is_ip_allowed(client_ip, api_key.ip_allowlist):
            raise AuthenticationFailed(f"Client IP address '{client_ip}' is not permitted for this API key.")

        # 8. Check organization active status
        if not api_key.organization.is_active:
            raise AuthenticationFailed("Tenant organization is inactive.")

        # 9. Establish ambient tenant context and PostgreSQL RLS
        set_current_organization(api_key.organization)
        request.organization = api_key.organization  # type: ignore[attr-defined]
        request.api_key = api_key  # type: ignore[attr-defined]

        # 10. Record usage and telemetry
        record_api_key_usage(api_key=api_key, ip_address=client_ip or None)

        # 11. Determine principal user
        user = api_key.user or api_key.created_by or ApiKeyPrincipal(api_key)

        return user, api_key


class ApiKeyAuthenticationScheme(OpenApiAuthenticationExtension):
    """drf-spectacular OpenAPI security scheme registration."""

    target_class = "apps.core.api.authentication.ApiKeyAuthentication"
    name = "ApiKeyAuth"

    def get_security_definition(self, auto_schema: Any) -> dict[str, Any]:
        return {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "Tenant API key. Format: bos_live_<prefix>_<secret>",
        }
