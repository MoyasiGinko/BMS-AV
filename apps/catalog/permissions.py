"""Catalog role permissions registration."""

from __future__ import annotations

from apps.core.permissions import register_permission

PERMISSIONS = {
    "catalog.view": "View products, categories, price lists, and units",
    "catalog.manage": "Create, update, delete, and import products and catalog data",
}


def register_catalog_permissions() -> None:
    """Register catalog permissions in core catalog."""
    for code, desc in PERMISSIONS.items():
        register_permission(code, description=desc, module="catalog")
