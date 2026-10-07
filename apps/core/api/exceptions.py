"""Standardized exception handling for Business OS REST API.

Transforms all DRF exceptions, validation errors, and domain exceptions
into the uniform error contract:
{
    "code": "<error_code>",
    "message": "<human_readable_message>",
    "details": <dict_or_list_or_null>,
    "request_id": "<uuid>"
}
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from apps.core.exceptions import (
    BusinessOSException,
    ConflictError,
    InvalidTransitionError,
    PermissionDeniedError,
    PlanEntitlementError,
    RecordNotFoundError,
    TenantAccessError,
)
from apps.core.exceptions import (
    ValidationError as DomainValidationError,
)

logger = logging.getLogger(__name__)

_DOMAIN_STATUS_MAP: dict[type[BusinessOSException], int] = {
    TenantAccessError: status.HTTP_403_FORBIDDEN,
    PermissionDeniedError: status.HTTP_403_FORBIDDEN,
    PlanEntitlementError: status.HTTP_403_FORBIDDEN,
    RecordNotFoundError: status.HTTP_404_NOT_FOUND,
    ConflictError: status.HTTP_409_CONFLICT,
    InvalidTransitionError: status.HTTP_409_CONFLICT,
    DomainValidationError: status.HTTP_400_BAD_REQUEST,
}

_EXC_CODE_RULES: list[tuple[tuple[type[Exception], ...], str]] = [
    ((exceptions.ValidationError, DomainValidationError), "validation_error"),
    ((exceptions.NotAuthenticated, exceptions.AuthenticationFailed), "not_authenticated"),
    ((exceptions.PermissionDenied, DjangoPermissionDenied), "permission_denied"),
    ((exceptions.NotFound, Http404), "not_found"),
    ((exceptions.MethodNotAllowed,), "method_not_allowed"),
    ((exceptions.Throttled,), "throttled"),
]

_STATUS_CODE_MAP: dict[int, str] = {
    status.HTTP_400_BAD_REQUEST: "validation_error",
    status.HTTP_401_UNAUTHORIZED: "not_authenticated",
    status.HTTP_403_FORBIDDEN: "permission_denied",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_429_TOO_MANY_REQUESTS: "throttled",
}


def custom_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Global DRF exception handler returning structured JSON error envelope."""
    request = context.get("request")
    request_id = getattr(request, "request_id", None) or getattr(request, "id", None)
    if not request_id and request is not None:
        request_id = request.headers.get("X-Request-ID")

    # 1. Try standard DRF exception handler
    response = exception_handler(exc, context)

    if response is not None:
        code = _extract_error_code(exc, response.status_code)
        message, details = _extract_message_and_details(response.data)

        error_data = {
            "code": code,
            "message": message,
            "details": details,
            "request_id": str(request_id) if request_id else None,
        }
        response.data = error_data
        if request_id:
            response["X-Request-ID"] = str(request_id)
        return response

    # 2. Handle Business OS domain exceptions
    if isinstance(exc, BusinessOSException):
        status_code = _DOMAIN_STATUS_MAP.get(type(exc), status.HTTP_400_BAD_REQUEST)
        error_data = {
            "code": exc.code,
            "message": exc.message,
            "details": exc.details if exc.details else None,
            "request_id": str(request_id) if request_id else None,
        }
        res = Response(error_data, status=status_code)
        if request_id:
            res["X-Request-ID"] = str(request_id)
        return res

    # 3. Handle standard Django exceptions
    if isinstance(exc, DjangoPermissionDenied):
        error_data = {
            "code": "permission_denied",
            "message": str(exc) or "Permission denied.",
            "details": None,
            "request_id": str(request_id) if request_id else None,
        }
        res = Response(error_data, status=status.HTTP_403_FORBIDDEN)
        if request_id:
            res["X-Request-ID"] = str(request_id)
        return res

    if isinstance(exc, Http404):
        error_data = {
            "code": "not_found",
            "message": str(exc) or "Resource not found.",
            "details": None,
            "request_id": str(request_id) if request_id else None,
        }
        res = Response(error_data, status=status.HTTP_404_NOT_FOUND)
        if request_id:
            res["X-Request-ID"] = str(request_id)
        return res

    # Let unhandled exceptions fall through to Django 500 handler
    return None


def _extract_error_code(exc: Exception, status_code: int) -> str:
    for exc_types, code in _EXC_CODE_RULES:
        if isinstance(exc, exc_types):
            return code
    return _STATUS_CODE_MAP.get(status_code, "api_error")


def _extract_message_and_details(data: Any) -> tuple[str, Any]:
    if isinstance(data, dict):
        if "detail" in data:
            msg = str(data["detail"])
            remaining = {k: v for k, v in data.items() if k != "detail"}
            return msg, remaining if remaining else None

        # Field validation errors dict
        first_key = next(iter(data.keys()), None)
        if first_key:
            first_val = data[first_key]
            first_err = str(first_val[0]) if isinstance(first_val, list) and first_val else str(first_val)
            msg = f"{first_key}: {first_err}" if first_key != "non_field_errors" else first_err
        else:
            msg = "Validation failed."
        return msg, data

    if isinstance(data, list):
        msg = str(data[0]) if data else "An error occurred."
        return msg, data

    return str(data), None
