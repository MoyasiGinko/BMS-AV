"""Customer accounts entity exporter."""

from __future__ import annotations

from typing import Any

from django.utils import timezone

from apps.customers.models import Customer
from apps.integrations.exporters.base import BaseEntityExporter
from apps.tenancy.models import Organization


class CustomerEntityExporter(BaseEntityExporter):
    entity_type = "customers"
    display_name = "Customers Directory"

    def export(
        self,
        organization: Organization,
        file_format: str,
        filters: dict[str, Any] | None = None,
    ) -> tuple[str, bytes, int]:
        filters = filters or {}
        qs = Customer.all_tenants.filter(organization=organization).order_by("name")

        status_filter = filters.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        headers = [
            "Customer Code",
            "Name",
            "Customer Type",
            "Status",
            "Email",
            "Phone",
            "Tax ID",
            "Current Balance",
            "Credit Limit",
            "Payment Terms (Days)",
            "Currency",
            "Notes",
            "Created Date",
        ]

        rows: list[list[Any]] = []
        for c in qs:
            rows.append(
                [
                    c.code,
                    c.name,
                    c.get_type_display(),
                    c.get_status_display(),
                    c.email or "",
                    c.phone or "",
                    c.tax_id or "",
                    float(c.current_balance),
                    float(c.credit_limit),
                    c.payment_terms_days,
                    c.currency,
                    c.notes or "",
                    c.created_at.strftime("%Y-%m-%d %H:%M"),
                ]
            )

        ts = timezone.now().strftime("%Y%m%d_%H%M%S")
        if file_format.lower() == "xlsx":
            return self.build_xlsx(f"customers_export_{ts}.xlsx", "Customers", headers, rows)
        return self.build_csv(f"customers_export_{ts}.csv", headers, rows)
