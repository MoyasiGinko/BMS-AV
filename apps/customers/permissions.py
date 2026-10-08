"""Customer role permissions registration."""

from __future__ import annotations

from apps.core.permissions import register_permission

PERMISSIONS = {
    "customers.view": "View customer profiles, contacts, and account statements",
    "customers.create": "Create new customer accounts and contacts",
    "customers.update": "Edit customer details, addresses, and credit limits",
    "customers.delete": "Delete customers without transaction history",
    "customers.adjust_balance": "Post manual balance adjustments to customer subledgers",
    "customers.export": "Export customer accounts and statement reports",
}


def register_customers_permissions() -> None:
    """Register customer permissions in the system permission catalog."""
    for code, desc in PERMISSIONS.items():
        register_permission(code, description=desc, module="customers")
