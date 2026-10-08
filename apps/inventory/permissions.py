"""Inventory role permissions registration."""

from __future__ import annotations

from apps.core.permissions import register_permission

PERMISSIONS = {
    "inventory.view": "View stock levels, warehouse inventory, and movements",
    "inventory.create": "Create stock transfers and count audits",
    "inventory.adjust": "Perform stock adjustments and write-offs",
    "inventory.transfer": "Confirm and dispatch warehouse stock transfers",
    "inventory.count": "Conduct and reconcile cycle counts",
    "inventory.manage": "Full inventory management access",
}


def register_inventory_permissions() -> None:
    """Register inventory permissions in the system permission catalog."""
    for code, desc in PERMISSIONS.items():
        register_permission(code, description=desc, module="inventory")
