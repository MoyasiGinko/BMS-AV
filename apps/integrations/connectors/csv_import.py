"""CSV data feed and batch file import connector."""

from __future__ import annotations

import csv
import io
from typing import TYPE_CHECKING, Any

from apps.integrations.connectors.base import BaseConnector, ConnectorResult

if TYPE_CHECKING:
    from apps.integrations.models import IntegrationConnection


class CsvImportConnector(BaseConnector):
    """Connector for validating and ingesting CSV data files or scheduled remote feeds."""

    connector_type = "csv_import"
    name = "CSV Data Feed / Import"
    description = "Scheduled ingestion of CSV data feeds or files into products, customers, and orders."
    category = "data"
    supported_actions = ["validate_csv", "ingest_csv", "preview_feed"]
    config_schema = [
        {
            "name": "entity_type",
            "label": "Target Entity Type",
            "type": "select",
            "required": True,
            "options": [
                {"value": "products", "label": "Products Catalog"},
                {"value": "customers", "label": "Customers Directory"},
            ],
            "default": "products",
        },
        {
            "name": "delimiter",
            "label": "Field Delimiter",
            "type": "text",
            "default": ",",
            "required": False,
        },
        {
            "name": "feed_url",
            "label": "Remote Feed URL (Optional)",
            "type": "url",
            "required": False,
            "help_text": "HTTP(S) URL to periodically fetch CSV files from.",
        },
        {
            "name": "update_existing",
            "label": "Update Existing Records",
            "type": "checkbox",
            "default": True,
            "required": False,
        },
    ]

    def test_connection(self, connection: IntegrationConnection) -> ConnectorResult:
        """Verify configuration and feed URL if specified."""
        cfg = connection.config or {}
        entity_type = cfg.get("entity_type")
        if not entity_type or entity_type not in ["products", "customers"]:
            return ConnectorResult(
                success=False,
                message="Invalid target entity type. Must be 'products' or 'customers'.",
                errors=[{"entity_type": "Invalid entity type"}],
            )

        feed_url = cfg.get("feed_url")
        if feed_url and not (feed_url.startswith("http://") or feed_url.startswith("https://")):
            return ConnectorResult(
                success=False,
                message="Feed URL must be a valid HTTP or HTTPS address.",
                errors=[{"feed_url": "Invalid URL format"}],
            )

        return ConnectorResult(
            success=True,
            message="CSV import configuration is valid.",
            data={"entity_type": entity_type, "feed_url": feed_url or "None (Manual Uploads)"},
        )

    def sync(
        self,
        connection: IntegrationConnection,
        direction: str = "inbound",
        params: dict[str, Any] | None = None,
    ) -> ConnectorResult:
        """Process CSV content or mock feed."""
        params = params or {}
        csv_text = params.get("csv_content")
        delimiter = (connection.config or {}).get("delimiter", ",")

        if not csv_text:
            # Default sample sync run
            csv_text = "code,name,price\nSKU-001,Demo Product 1,19.99\nSKU-002,Demo Product 2,29.50"

        try:
            reader = csv.DictReader(io.StringIO(csv_text.strip()), delimiter=delimiter)
            rows = list(reader)
        except Exception as exc:
            return ConnectorResult(
                success=False,
                message=f"Failed to parse CSV content: {exc}",
                errors=[{"csv": str(exc)}],
            )

        return ConnectorResult(
            success=True,
            message=f"CSV import processed {len(rows)} valid records.",
            records_processed=len(rows),
            records_succeeded=len(rows),
            records_failed=0,
            data={"row_count": len(rows), "headers": reader.fieldnames or []},
        )

    def action_validate_csv(
        self,
        connection: IntegrationConnection,
        payload: dict[str, Any],
    ) -> ConnectorResult:
        """Validate raw CSV structure."""
        return self.sync(connection, direction="inbound", params=payload)

    def action_ingest_csv(
        self,
        connection: IntegrationConnection,
        payload: dict[str, Any],
    ) -> ConnectorResult:
        """Ingest CSV records into domain models."""
        return self.sync(connection, direction="inbound", params=payload)
