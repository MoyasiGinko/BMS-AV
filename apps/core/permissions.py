"""Three-layer permission engine for Business OS.

Layer 1: Feature Entitlement (Plan) -> `feature_required('module.feature')`
Layer 2: Role Permission (Org customizable) -> `permission_required('app.action')`
Layer 3: Object Scope (Branch/Warehouse) -> `scope_queryset(qs, user)`
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import TYPE_CHECKING, Any

from django.apps import apps
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db.models import Q, QuerySet
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect
from django.utils.translation import gettext as _

from apps.core.tenant_context import get_current_organization

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Permission Registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PermissionDefinition:
    """Metadata describing a role permission code."""

    code: str
    description: str
    module: str


_PERMISSIONS: dict[str, PermissionDefinition] = {}


def register_permission(code: str, *, description: str, module: str) -> None:
    """Register a permission code in the system catalog."""
    _PERMISSIONS[code] = PermissionDefinition(code=code, description=description, module=module)


def get_permission(code: str) -> PermissionDefinition | None:
    """Lookup definition of a permission code."""
    return _PERMISSIONS.get(code)


def list_permissions() -> list[PermissionDefinition]:
    """Return all registered system permissions."""
    return list(_PERMISSIONS.values())


# Standard permissions catalog
_CORE_PERMISSIONS = [
    ("tenancy.manage", "Manage organization settings, branches, and warehouses", "tenancy"),
    ("users.manage", "Invite and manage member roles and permissions", "tenancy"),
    ("catalog.view", "View products, categories, units, and price lists", "catalog"),
    ("catalog.manage", "Create, edit, or archive products and prices", "catalog"),
    ("inventory.view", "View stock levels and warehouse locations", "inventory"),
    ("inventory.manage", "Perform stock movements, adjustments, and counts", "inventory"),
    ("sales.view", "View quotes, orders, invoices, and credit notes", "sales"),
    ("sales.create", "Create sales orders and draft invoices", "sales"),
    ("sales.manage", "Approve invoices, issue credit notes, and void sales", "sales"),
    ("purchasing.view", "View purchase orders and vendor bills", "purchasing"),
    ("purchasing.manage", "Create and approve purchase orders and bills", "purchasing"),
    ("customers.view", "View customer profiles, contacts, and balances", "customers"),
    ("customers.manage", "Create and edit customer records and credit limits", "customers"),
    ("accounting.view", "View chart of accounts, journals, and fiscal periods", "accounting"),
    ("accounting.post", "Post or reverse journal entries", "accounting"),
    ("accounting.manage", "Close fiscal periods and configure account mappings", "accounting"),
    ("pos.access", "Open registers, access POS cash terminal", "pos"),
    ("pos.manage", "Close cash shifts, manage cash variances and receipts", "pos"),
    ("hr.view", "View employee profiles and departments", "hr"),
    ("hr.manage", "Manage employees, contracts, and leave", "hr"),
    ("payroll.view", "View payslips and payroll summaries", "payroll"),
    ("payroll.manage", "Process and approve payroll runs", "payroll"),
    ("reports.view", "View operational and financial reports", "reports"),
    ("reports.export", "Export reports to CSV, XLSX, and PDF", "reports"),
    ("settings.manage", "Configure tax rates, currencies, sequences, and integrations", "settings"),
]

for _code, _desc, _mod in _CORE_PERMISSIONS:
    register_permission(_code, description=_desc, module=_mod)


# ---------------------------------------------------------------------------
# Layer 1: Feature Entitlement (Plan)
# ---------------------------------------------------------------------------

_ENTITLEMENT_CHECKERS: list[Callable[[Any, str], bool | None]] = []
_FEATURE_OVERRIDES: dict[tuple[int, str], bool] = {}


def register_entitlement_checker(fn: Callable[[Any, str], bool | None]) -> None:
    """Register a custom checker hook for feature entitlements (used by billing)."""
    _ENTITLEMENT_CHECKERS.insert(0, fn)


def clear_entitlement_checkers() -> None:
    """Clear all registered entitlement checkers."""
    _ENTITLEMENT_CHECKERS.clear()


def set_feature_override(organization_id: int, feature_code: str, is_allowed: bool) -> None:
    """Explicitly enable or disable a feature for an organization (testing/admin overrides)."""
    _FEATURE_OVERRIDES[(organization_id, feature_code)] = is_allowed


def clear_feature_overrides() -> None:
    """Clear all active feature overrides."""
    _FEATURE_OVERRIDES.clear()


def has_feature_entitlement(organization: Any, feature_code: str) -> bool:
    """Layer 1: Check whether the organization is entitled to a feature under its subscription."""
    if organization is None:
        return False

    org_id = getattr(organization, "pk", getattr(organization, "id", None))
    if org_id is not None and (org_id, feature_code) in _FEATURE_OVERRIDES:
        return _FEATURE_OVERRIDES[(org_id, feature_code)]

    for checker in _ENTITLEMENT_CHECKERS:
        res = checker(organization, feature_code)
        if res is not None:
            return res

    return True


check_organization_feature_entitlement = has_feature_entitlement


# ---------------------------------------------------------------------------
# Layer 2: Role Permission
# ---------------------------------------------------------------------------


def match_permission_pattern(granted_perms: list[str] | set[str], required_code: str) -> bool:
    """Check if required_code matches any granted permission (supports '*' and 'app.*')."""
    if "*" in granted_perms:
        return True
    if required_code in granted_perms:
        return True
    if "." in required_code:
        wildcard = required_code.split(".", 1)[0] + ".*"
        if wildcard in granted_perms:
            return True
    return False


def get_user_membership(user: Any, organization: Any = None) -> Any:
    """Dynamically fetch user's active membership in the organization."""
    if not getattr(user, "is_authenticated", False):
        return None

    org_id = getattr(organization, "pk", getattr(organization, "id", None))
    if org_id is None:
        org = get_current_organization()
        org_id = getattr(org, "pk", getattr(org, "id", None))
    if org_id is None:
        return None

    cache_attr = f"_cached_membership_{org_id}"
    if hasattr(user, cache_attr):
        return getattr(user, cache_attr)

    try:
        membership_model = apps.get_model("tenancy", "Membership")
        membership = (
            membership_model.all_tenants.filter(
                user=user,
                organization_id=org_id,
                status="active",
            )
            .select_related("role", "organization")
            .first()
        )
        with contextlib.suppress(Exception):
            setattr(user, cache_attr, membership)
        return membership
    except LookupError, AttributeError:
        return None


def has_permission(
    user: Any,
    permission_code: str,
    *,
    organization: Any = None,
) -> bool:
    """Layer 2: Verify user role has the required permission code in this organization."""
    if not getattr(user, "is_authenticated", False):
        return False

    if getattr(user, "is_superuser", False):
        return True

    membership = get_user_membership(user, organization)
    if membership is None:
        return False

    if getattr(membership, "is_owner", False):
        return True

    role = getattr(membership, "role", None)
    if role is None:
        return False

    role_perms = getattr(role, "permissions", None) or []
    return match_permission_pattern(role_perms, permission_code)


# ---------------------------------------------------------------------------
# Layer 3: Object Scope (Branch / Warehouse)
# ---------------------------------------------------------------------------


def get_user_allowed_branch_ids(user: Any, *, organization: Any = None) -> list[int] | None:
    """Return list of allowed branch IDs, or None if the user has unrestricted global access."""
    if not getattr(user, "is_authenticated", False):
        return []
    if getattr(user, "is_superuser", False):
        return None

    membership = get_user_membership(user, organization)
    if membership is None:
        return []

    role = getattr(membership, "role", None)
    role_perms = getattr(role, "permissions", None) or []
    if getattr(membership, "is_owner", False) or "*" in role_perms:
        return None

    try:
        mb_model = apps.get_model("tenancy", "MembershipBranch")
        branch_ids = list(
            mb_model.all_tenants.filter(membership=membership).values_list("branch_id", flat=True)
        )
        return branch_ids or None
    except LookupError, AttributeError:
        return None


def _build_scope_filter(field_names: set[str], allowed: set[int]) -> Q | None:
    """Build a Q filter expression based on available model fields for branch scoping."""
    if "branch" in field_names:
        return Q(branch_id__in=allowed)
    if "warehouse" in field_names:
        return Q(warehouse__branch_id__in=allowed)
    if "register" in field_names:
        return Q(register__branch_id__in=allowed)
    if "shift" in field_names:
        return Q(shift__register__branch_id__in=allowed)
    if "purchase_order" in field_names:
        return Q(purchase_order__branch_id__in=allowed)

    transfer_q = Q()
    if "source_branch" in field_names and "destination_branch" in field_names:
        transfer_q |= Q(source_branch_id__in=allowed) | Q(destination_branch_id__in=allowed)
    if "source_warehouse" in field_names and "destination_warehouse" in field_names:
        transfer_q |= Q(source_warehouse__branch_id__in=allowed) | Q(
            destination_warehouse__branch_id__in=allowed
        )
    return transfer_q if transfer_q else None


def scope_queryset(
    queryset: QuerySet[Any],
    user: Any,
    *,
    organization: Any = None,
    branch_field: str = "branch",
) -> QuerySet[Any]:
    """Layer 3: Scope a queryset according to the user's branch assignments."""
    allowed = get_user_allowed_branch_ids(user, organization=organization)
    model = getattr(queryset, "model", None)
    if allowed is None or model is None:
        return queryset
    if not allowed:
        return queryset.none()

    if branch_field in ("self", "id", "pk") or getattr(model._meta, "model_name", "") == "branch":
        return queryset.filter(id__in=allowed)

    if branch_field != "branch":
        return queryset.filter(**{f"{branch_field}_id__in": allowed})

    scope_filter = _build_scope_filter({f.name for f in model._meta.get_fields()}, set(allowed))
    return queryset.filter(scope_filter) if scope_filter is not None else queryset


def _extract_object_branch_ids(obj: Any, branch_field: str) -> set[int] | None:
    """Extract all relevant branch IDs associated with an object instance."""
    meta = getattr(obj, "_meta", None)
    model_name = getattr(meta, "model_name", "") if meta else ""
    if branch_field in ("self", "id", "pk") or model_name == "branch":
        pk = getattr(obj, "pk", None)
        return {pk} if pk is not None else None

    if branch_field != "branch" and hasattr(obj, branch_field):
        target = getattr(obj, branch_field, None)
        target_id = getattr(obj, f"{branch_field}_id", getattr(target, "pk", None))
        return {target_id} if target_id is not None else None

    bids: set[int] = set()
    b_id = getattr(obj, "branch_id", getattr(getattr(obj, "branch", None), "pk", None))
    if b_id is not None:
        bids.add(b_id)

    wh = getattr(obj, "warehouse", None)
    if wh is not None and getattr(wh, "branch_id", None) is not None:
        bids.add(wh.branch_id)

    reg = getattr(obj, "register", None)
    if reg is not None and getattr(reg, "branch_id", None) is not None:
        bids.add(reg.branch_id)

    shift = getattr(obj, "shift", None)
    if shift and getattr(shift, "register", None):
        bids.add(shift.register.branch_id)

    po = getattr(obj, "purchase_order", None)
    if po is not None and getattr(po, "branch_id", None) is not None:
        bids.add(po.branch_id)

    for attr in ("source_branch_id", "destination_branch_id"):
        val = getattr(obj, attr, None)
        if val is not None:
            bids.add(val)
    for wh_attr in ("source_warehouse", "destination_warehouse"):
        wh_obj = getattr(obj, wh_attr, None)
        if wh_obj is not None and getattr(wh_obj, "branch_id", None) is not None:
            bids.add(wh_obj.branch_id)

    return bids if bids else None


def check_object_scope(
    user: Any,
    obj: Any,
    *,
    organization: Any = None,
    branch_field: str = "branch",
) -> bool:
    """Layer 3: Check whether a user is allowed to access a specific object instance."""
    if obj is None:
        return True

    allowed = get_user_allowed_branch_ids(user, organization=organization)
    if allowed is None:
        return True
    if not allowed:
        return False

    obj_branch_ids = _extract_object_branch_ids(obj, branch_field)
    if obj_branch_ids is None:
        return True
    return bool(obj_branch_ids.intersection(allowed))


# ---------------------------------------------------------------------------
# View Decorators
# ---------------------------------------------------------------------------


def feature_required(feature_code: str) -> Callable[[Callable], Callable]:
    """Decorator for views enforcing Layer 1: Plan Feature Entitlement."""

    def decorator(view_func: Callable) -> Callable:
        @wraps(view_func)
        def _wrapped_view(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            org = getattr(request, "organization", None) or get_current_organization()
            if not has_feature_entitlement(org, feature_code):
                raise PermissionDenied(
                    _("Your organization's current plan does not include '%(feature)s'.")
                    % {"feature": feature_code}
                )
            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator


def permission_required(
    permission_code: str,
    *,
    raise_exception: bool = True,
) -> Callable[[Callable], Callable]:
    """Decorator for views enforcing Layer 2: Role Permission."""

    def decorator(view_func: Callable) -> Callable:
        @wraps(view_func)
        def _wrapped_view(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            user = getattr(request, "user", None)
            if not user or not user.is_authenticated:
                return redirect(f"{settings.LOGIN_URL}?next={request.path}")

            org = getattr(request, "organization", None) or get_current_organization()
            if not has_permission(user, permission_code, organization=org):
                if raise_exception:
                    raise PermissionDenied(
                        _("You do not have the required permission: '%(perm)s'.") % {"perm": permission_code}
                    )
                return HttpResponseForbidden(_("Permission denied."))
            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator


# ---------------------------------------------------------------------------
# View Mixins (CBV)
# ---------------------------------------------------------------------------


class FeatureRequiredMixin:
    """CBV Mixin enforcing Layer 1: Feature Entitlement."""

    required_feature: str = ""

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if self.required_feature:
            org = getattr(request, "organization", None) or get_current_organization()
            if not has_feature_entitlement(org, self.required_feature):
                raise PermissionDenied(
                    _("Your organization's current plan does not include '%(feature)s'.")
                    % {"feature": self.required_feature}
                )
        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]


class PermissionRequiredMixin:
    """CBV Mixin enforcing Layer 2: Role Permission."""

    required_permission: str = ""

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return redirect(f"{settings.LOGIN_URL}?next={request.path}")

        if self.required_permission:
            org = getattr(request, "organization", None) or get_current_organization()
            if not has_permission(user, self.required_permission, organization=org):
                raise PermissionDenied(
                    _("You do not have the required permission: '%(perm)s'.")
                    % {"perm": self.required_permission}
                )
        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]


class ObjectScopeMixin:
    """CBV Mixin enforcing Layer 3: Branch / Object Scope filtering on get_queryset."""

    branch_field: str = "branch"
    request: HttpRequest

    def get_queryset(self) -> QuerySet[Any]:
        qs = super().get_queryset()  # type: ignore[misc]
        req = getattr(self, "request", None)
        user = getattr(req, "user", None)
        org = getattr(req, "organization", None)
        return scope_queryset(
            qs,
            user,
            organization=org,
            branch_field=self.branch_field,
        )
