"""DRF permission classes implementing the 3-layer security engine:

Layer 1: Feature Entitlement (Plan) -> HasFeatureEntitlement
Layer 2: Role Permission (Role->Permission code) -> HasRolePermission
Layer 3: Object Scope (Branch/Warehouse/Record level) -> HasObjectScope
"""

from __future__ import annotations

from typing import Any

from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from apps.core.exceptions import PermissionDeniedError, PlanEntitlementError
from apps.core.permissions import (
    check_object_scope,
    has_feature_entitlement,
    has_permission,
)


def _get_request_org(request: Request, view: Any) -> Any:
    """Helper to extract active organization from request or view."""
    org = getattr(request, "organization", None)
    if org is None and hasattr(view, "get_tenant"):
        try:
            org = view.get_tenant()
        except Exception:
            org = None
    return org


class HasFeatureEntitlement(BasePermission):
    """Layer 1: Verifies the tenant organization is entitled to the feature/module."""

    message = "Your organization plan is not entitled to this feature."
    code = "plan_not_entitled"

    def has_permission(self, request: Request, view: Any) -> bool:
        feature_code = getattr(view, "feature_code", None) or getattr(view, "module_key", None)
        if not feature_code:
            return True

        org = _get_request_org(request, view)
        if not org:
            return True

        if not has_feature_entitlement(org, feature_code):
            raise PlanEntitlementError(
                f"Feature '{feature_code}' is not included in your organization's subscription plan."
            )
        return True


class HasRolePermission(BasePermission):
    """Layer 2: Verifies user has the required permission code in the organization."""

    message = "You do not have permission to perform this action."
    code = "permission_denied"

    def has_permission(self, request: Request, view: Any) -> bool:
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False

        # Superusers and staff have system-level access
        if getattr(user, "is_superuser", False) or getattr(user, "is_staff", False):
            return True

        perm_code: str | None = None
        action = getattr(view, "action", None)
        permission_map = getattr(view, "permission_map", None)

        if isinstance(permission_map, dict) and action in permission_map:
            perm_code = permission_map[action]
        elif hasattr(view, "required_permission"):
            perm_code = getattr(view, "required_permission", None)

        if not perm_code:
            return True

        org = _get_request_org(request, view)
        if not org:
            return False

        if not has_permission(user, perm_code, organization=org):
            raise PermissionDeniedError(f"Your role does not grant permission '{perm_code}'.")
        return True


class HasObjectScope(BasePermission):
    """Layer 3: Verifies user has access to this specific object (e.g. branch or warehouse scope)."""

    message = "You do not have access to this record within your branch scope."
    code = "object_scope_denied"

    def has_object_permission(self, request: Request, view: Any, obj: Any) -> bool:
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False

        if getattr(user, "is_superuser", False) or getattr(user, "is_staff", False):
            return True

        org = _get_request_org(request, view)
        if not org:
            return False

        if not check_object_scope(user, obj, organization=org):
            raise PermissionDeniedError("Access to this record is restricted to authorized branch members.")
        return True


class HasModuleAccess(BasePermission):
    """Convenience permission checking both feature entitlement and basic module view."""

    def has_permission(self, request: Request, view: Any) -> bool:
        feature_check = HasFeatureEntitlement()
        if not feature_check.has_permission(request, view):
            return False

        module_key = getattr(view, "module_key", None)
        if not module_key:
            return True

        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False

        if getattr(user, "is_superuser", False) or getattr(user, "is_staff", False):
            return True

        org = _get_request_org(request, view)
        if not org:
            return False

        # Check if user has either module.view or module.manage
        if has_permission(user, f"{module_key}.view", organization=org) or has_permission(
            user, f"{module_key}.manage", organization=org
        ):
            return True

        raise PermissionDeniedError(f"You do not have access to the {module_key} module.")
