"""Idempotency support for mutating API endpoints.

Stores request hash and response payload for 24 hours in Redis.
Replaying the same key with the same payload returns the cached response
with the `Idempotent-Replayed: true` header. Replaying with different payload
raises a ConflictError (409/400).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections.abc import Callable
from functools import wraps
from typing import Any

from django.core.cache import cache
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.exceptions import ConflictError, ValidationError
from apps.core.tenant_context import get_current_organization

IDEMPOTENCY_KEY_PARAMETER = OpenApiParameter(
    name="Idempotency-Key",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.HEADER,
    required=False,
    description=(
        "Unique idempotency key (UUID or client token) ensuring mutating operations "
        "execute at most once. Cached for 24 hours."
    ),
)


def _compute_request_hash(request: Request) -> str:
    """Compute a deterministic SHA-256 hash of the request content."""
    body_representation: str = ""
    try:
        if hasattr(request, "data") and request.data is not None:
            body_representation = json.dumps(request.data, sort_keys=True, default=str)
        elif hasattr(request, "body"):
            body_representation = request.body.decode("utf-8", errors="replace")
    except Exception:
        body_representation = ""

    components = [
        (request.method or "GET").upper(),
        request.path,
        request.META.get("QUERY_STRING", ""),
        body_representation,
    ]
    raw = "|".join(components)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _extract_request(args: tuple[Any, ...]) -> Request | None:
    for arg in args:
        if isinstance(arg, Request):
            return arg
        if hasattr(arg, "request") and isinstance(arg.request, Request):
            return arg.request
    return None


def _get_idempotency_key(request: Request, required: bool) -> str | None:
    key = request.headers.get("Idempotency-Key") or request.META.get("HTTP_IDEMPOTENCY_KEY")
    if not key:
        if required:
            raise ValidationError(
                "Idempotency-Key header is required for this operation.",
                code="idempotency_key_required",
            )
        return None

    cleaned = key.strip()
    if not cleaned or len(cleaned) > 128:
        raise ValidationError(
            "Invalid Idempotency-Key header. Must be 1-128 characters.",
            code="invalid_idempotency_key",
        )
    return cleaned


def _check_cached_response(cached_entry: dict[str, Any], req_hash: str) -> Response:
    if cached_entry.get("request_hash") != req_hash:
        raise ConflictError(
            "Idempotency key reused with different request payload.",
            code="idempotency_key_mismatch",
        )
    if cached_entry.get("status") == "processing":
        raise ConflictError(
            "A request with this Idempotency-Key is currently in progress.",
            code="request_in_progress",
        )

    res = Response(cached_entry.get("data"), status=cached_entry.get("status_code", 200))
    res["Idempotent-Replayed"] = "true"
    res["X-Cache-Lookup"] = "HIT"
    return res


def idempotent(
    fn: Callable[..., Response] | None = None,
    *,
    ttl: int = 86400,
    required: bool = False,
) -> Any:
    """Decorator to enforce or handle Idempotency-Key header on DRF actions/views."""

    def decorator(view_func: Callable[..., Response]) -> Callable[..., Response]:
        @wraps(view_func)
        def wrapper(*args: Any, **kwargs: Any) -> Response:
            request = _extract_request(args)
            if request is None:
                return view_func(*args, **kwargs)

            idempotency_key = _get_idempotency_key(request, required)
            if not idempotency_key:
                return view_func(*args, **kwargs)

            org = getattr(request, "organization", None)
            if org is None and args and hasattr(args[0], "get_tenant"):
                with contextlib.suppress(Exception):
                    org = args[0].get_tenant()
            if org is None:
                org = get_current_organization()
            org_id = getattr(org, "pk", getattr(org, "id", "no_org"))
            user = getattr(request, "user", None)
            user_id = getattr(user, "pk", getattr(user, "id", "anon"))
            cache_key = f"idempotency:{org_id}:{user_id}:{idempotency_key}"

            req_hash = _compute_request_hash(request)
            cached_entry = cache.get(cache_key)
            if cached_entry is not None:
                return _check_cached_response(cached_entry, req_hash)

            cache.set(
                cache_key,
                {"request_hash": req_hash, "status": "processing"},
                timeout=120,
            )

            try:
                response = view_func(*args, **kwargs)
                if isinstance(response, Response) and response.status_code < 500:
                    cache.set(
                        cache_key,
                        {
                            "request_hash": req_hash,
                            "status_code": response.status_code,
                            "data": response.data,
                        },
                        timeout=ttl,
                    )
                else:
                    cache.delete(cache_key)
                return response
            except Exception:
                cache.delete(cache_key)
                raise

        return wrapper

    if fn is not None:
        return decorator(fn)
    return decorator
