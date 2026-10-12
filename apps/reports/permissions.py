"""Permission helpers for the Reports module."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import PermissionDenied

from apps.core.permissions import has_feature_entitlement, has_permission, register_permission

PERMISSIONS = {
    "reports.view": "View operational and financial reports",
    "reports.export": "Export operational reports to CSV, XLSX, and PDF",
}


def register_reports_permissions() -> None:
    """Register report permissions in the system catalog."""
    for code, desc in PERMISSIONS.items():
        register_permission(code, description=desc, module="reports")


register_reports_permissions()


def check_reports_view_permission(user: Any, organization: Any) -> None:
    """Verify tenant has reports entitlement and user has reports.view or sales.view."""
    if not has_feature_entitlement(organization, "reports"):
        raise PermissionDenied("Reports module is not included in current plan subscription.")

    if not (
        has_permission(user, "reports.view", organization=organization)
        or has_permission(user, "sales.view", organization=organization)
    ):
        raise PermissionDenied("You do not have permission to view reports.")


def check_reports_export_permission(user: Any, organization: Any) -> None:
    """Verify tenant has reports entitlement and user has reports.export permission."""
    check_reports_view_permission(user, organization)

    if not has_permission(user, "reports.export", organization=organization):
        raise PermissionDenied("You do not have permission to export reports.")


def check_hr_reports_permission(user: Any, organization: Any) -> None:
    """Verify tenant has reports entitlement and user has reports.view or hr.view."""
    if not has_feature_entitlement(organization, "reports"):
        raise PermissionDenied("Reports module is not included in current plan subscription.")

    if not (
        has_permission(user, "reports.view", organization=organization)
        or has_permission(user, "hr.view", organization=organization)
    ):
        raise PermissionDenied("You do not have permission to view HR reports.")


def check_payroll_reports_permission(user: Any, organization: Any) -> None:
    """Verify tenant has reports entitlement and user has reports.view or payroll.view."""
    if not has_feature_entitlement(organization, "reports"):
        raise PermissionDenied("Reports module is not included in current plan subscription.")

    if not (
        has_permission(user, "reports.view", organization=organization)
        or has_permission(user, "payroll.view", organization=organization)
    ):
        raise PermissionDenied("You do not have permission to view Payroll reports.")
