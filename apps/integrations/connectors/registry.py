"""Central connector registry for discovering and managing integration adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.integrations.connectors.base import BaseConnector
from apps.integrations.connectors.csv_import import CsvImportConnector
from apps.integrations.connectors.fake_payments import FakePaymentsConnector
from apps.integrations.connectors.fake_sms import FakeSmsConnector
from apps.integrations.connectors.generic_rest import GenericRestConnector
from apps.integrations.connectors.smtp_email import SmtpEmailConnector
from apps.integrations.connectors.zapier_compat import ZapierCompatConnector

if TYPE_CHECKING:
    pass


class ConnectorRegistry:
    """Registry maintaining available connector implementations."""

    def __init__(self) -> None:
        self._connectors: dict[str, BaseConnector] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register the standard built-in connectors."""
        self.register(GenericRestConnector())
        self.register(CsvImportConnector())
        self.register(FakePaymentsConnector())
        self.register(FakeSmsConnector())
        self.register(SmtpEmailConnector())
        self.register(ZapierCompatConnector())

    def register(self, connector: BaseConnector) -> None:
        """Register a new connector instance."""
        self._connectors[connector.connector_type] = connector

    def get(self, connector_type: str) -> BaseConnector:
        """Retrieve connector by type identifier."""
        if connector_type not in self._connectors:
            raise ValueError(f"Unknown integration connector: '{connector_type}'")
        return self._connectors[connector_type]

    def get_all(self) -> dict[str, BaseConnector]:
        """Return all registered connectors."""
        return dict(self._connectors)

    def get_gallery_metadata(self) -> list[dict[str, Any]]:
        """Return rich metadata for the integration connectors gallery UI."""
        gallery = []
        for c in self._connectors.values():
            gallery.append(
                {
                    "connector_type": c.connector_type,
                    "name": c.name,
                    "description": c.description,
                    "category": c.category,
                    "supported_actions": c.supported_actions,
                    "config_schema": c.config_schema,
                }
            )
        return gallery


# Global singleton registry instance
connector_registry = ConnectorRegistry()
