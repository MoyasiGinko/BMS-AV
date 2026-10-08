"""Accounting role permissions registration."""

from __future__ import annotations

from apps.core.permissions import register_permission

PERMISSIONS = {
    "accounting.view": "View chart of accounts, journal entries, and general ledger reports",
    "accounting.post": "Post journal entries to the general ledger",
    "accounting.close_period": "Close and reopen accounting fiscal periods",
    "accounting.manage": "Create, update, and manage accounts and mappings",
}


def register_accounting_permissions() -> None:
    """Register accounting permissions in core catalog."""
    for code, desc in PERMISSIONS.items():
        register_permission(code, description=desc, module="accounting")
