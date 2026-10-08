"""Permissions definition for the Sales and Invoicing module."""

from apps.core.permissions import register_permission

PERMISSIONS = {
    "sales.view": "View quotes, sales orders, invoices, and credit notes",
    "sales.create": "Create quotes, sales orders, invoices, and credit notes",
    "sales.update": "Edit draft sales documents",
    "sales.delete": "Delete draft sales documents",
    "sales.confirm": "Confirm sales orders and post invoices or credit notes to ledgers",
    "sales.payment": "Receive, allocate, refund, and void customer payments",
    "sales.void": "Void posted invoices, credit notes, and payments",
    "sales.manage": "Full access to sales configurations and operations",
}


def register_sales_permissions() -> None:
    """Register sales permissions in the system permission catalog."""
    for code, desc in PERMISSIONS.items():
        register_permission(code, description=desc, module="sales")
