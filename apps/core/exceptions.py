"""Core business exceptions hierarchy for Business OS."""

from __future__ import annotations

from typing import Any


class BusinessOSError(Exception):
    """Base class for all application and domain exceptions."""

    default_message = "An unexpected business exception occurred."
    default_code = "business_error"

    def __init__(
        self,
        message: str | None = None,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.code = code or self.default_code
        self.details = details or {}
        super().__init__(self.message)


BusinessOSException = BusinessOSError


class TenantAccessError(BusinessOSError):
    """Raised when tenant context is missing or cross-tenant access is attempted."""

    default_message = "Active organization context is missing or access is denied."
    default_code = "tenant_access_denied"


class PermissionDeniedError(BusinessOSError):
    """Raised when the user's role lacks the required permission code."""

    default_message = "You do not have permission to perform this action."
    default_code = "permission_denied"


class PlanEntitlementError(BusinessOSError):
    """Raised when the organization's subscription plan does not entitle a module or feature."""

    default_message = "Feature not available on your current plan."
    default_code = "plan_not_entitled"


class InvalidTransitionError(BusinessOSError):
    """Raised when a document or entity attempts an illegal state machine transition."""

    default_message = "Invalid state transition."
    default_code = "invalid_transition"


class ValidationError(BusinessOSError):
    """Raised when domain business rules are violated."""

    default_message = "Validation error."
    default_code = "validation_error"


class RecordNotFoundError(BusinessOSError):
    """Raised when a requested resource is not found within the tenant scope."""

    default_message = "Record not found."
    default_code = "not_found"


class ConflictError(BusinessOSError):
    """Raised when a concurrent modification or uniqueness conflict occurs."""

    default_message = "A conflict occurred while processing the request."
    default_code = "conflict"
