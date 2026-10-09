"""Registry of entity importers."""

from __future__ import annotations

from apps.integrations.importers.base import BaseEntityImporter
from apps.integrations.importers.customers import CustomerImporter
from apps.integrations.importers.products import ProductImporter

_IMPORTERS: dict[str, type[BaseEntityImporter]] = {
    "products": ProductImporter,
    "customers": CustomerImporter,
}


def get_importer(entity_type: str) -> BaseEntityImporter:
    """Retrieve an instantiated entity importer by entity type slug."""
    importer_cls = _IMPORTERS.get(entity_type.lower())
    if not importer_cls:
        raise ValueError(
            f"No importer registered for entity type '{entity_type}'. Supported: {list(_IMPORTERS.keys())}"
        )
    return importer_cls()


def list_available_importers() -> list[dict[str, str]]:
    """Return available entity importers for UI selection."""
    return [
        {
            "entity_type": "products",
            "name": "Products Catalog",
            "description": "Items, variants, SKU, pricing, categories, and units",
        },
        {
            "entity_type": "customers",
            "name": "Customers Directory",
            "description": "Customer profiles, contact details, payment terms, and credit limits",
        },
    ]
