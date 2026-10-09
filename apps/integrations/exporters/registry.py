"""Registry of entity exporters."""

from __future__ import annotations

from apps.integrations.exporters.base import BaseEntityExporter
from apps.integrations.exporters.customers import CustomerEntityExporter
from apps.integrations.exporters.products import ProductEntityExporter

_EXPORTERS: dict[str, type[BaseEntityExporter]] = {
    "products": ProductEntityExporter,
    "customers": CustomerEntityExporter,
}


def get_exporter(entity_type: str) -> BaseEntityExporter:
    """Retrieve an instantiated entity exporter by entity type slug."""
    exporter_cls = _EXPORTERS.get(entity_type.lower())
    if not exporter_cls:
        raise ValueError(
            f"No exporter registered for entity type '{entity_type}'. Supported: {list(_EXPORTERS.keys())}"
        )
    return exporter_cls()
