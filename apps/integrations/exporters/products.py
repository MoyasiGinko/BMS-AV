"""Product catalog entity exporter."""

from __future__ import annotations

from typing import Any

from django.utils import timezone

from apps.catalog.models import Product
from apps.integrations.exporters.base import BaseEntityExporter
from apps.tenancy.models import Organization


class ProductEntityExporter(BaseEntityExporter):
    entity_type = "products"
    display_name = "Products Catalog"

    def export(
        self,
        organization: Organization,
        file_format: str,
        filters: dict[str, Any] | None = None,
    ) -> tuple[str, bytes, int]:
        filters = filters or {}
        qs = (
            Product.all_tenants.filter(organization=organization)
            .select_related("category", "unit", "tax_code")
            .order_by("name")
        )

        category_id = filters.get("category_id")
        if category_id:
            qs = qs.filter(category_id=category_id)

        is_active = filters.get("is_active")
        if is_active is not None:
            qs = qs.filter(is_active=is_active)

        headers = [
            "SKU",
            "Name",
            "Type",
            "Category",
            "Unit",
            "Cost Price",
            "Selling Price",
            "Barcode",
            "Description",
            "Tax Code",
            "Is Active",
            "Created Date",
        ]

        rows: list[list[Any]] = []
        for p in qs:
            rows.append(
                [
                    p.sku,
                    p.name,
                    p.get_type_display(),
                    p.category.name if p.category else "",
                    p.unit.code if p.unit else "",
                    float(p.cost_price),
                    float(p.selling_price),
                    p.barcode or "",
                    p.description or "",
                    p.tax_code.code if p.tax_code else "",
                    "Yes" if p.is_active else "No",
                    p.created_at.strftime("%Y-%m-%d %H:%M"),
                ]
            )

        ts = timezone.now().strftime("%Y%m%d_%H%M%S")
        if file_format.lower() == "xlsx":
            return self.build_xlsx(f"products_export_{ts}.xlsx", "Products", headers, rows)
        return self.build_csv(f"products_export_{ts}.csv", headers, rows)
