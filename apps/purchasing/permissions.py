"""Permissions definition for the Purchasing and Vendor Management module."""

from apps.core.permissions import register_permission

PERMISSIONS = {
    "purchasing.view": "View suppliers, purchase orders, goods receipts, bills, and returns",
    "purchasing.create": "Create suppliers, purchase orders, goods receipts, and bills",
    "purchasing.update": "Edit draft purchase documents and supplier details",
    "purchasing.delete": "Delete draft purchase documents and archive suppliers",
    "purchasing.approve": "Approve purchase orders",
    "purchasing.receive": "Receive goods receipts and issue stock into warehouse",
    "purchasing.post": "Post supplier bills and purchase returns to general ledger",
    "purchasing.payment": "Disburse and allocate supplier payments",
    "purchasing.manage": "Full administrative access to purchasing configurations and workflows",
}


def register_purchasing_permissions() -> None:
    """Register purchasing permissions in the system permission catalog."""
    for code, desc in PERMISSIONS.items():
        register_permission(code, description=desc, module="purchasing")
