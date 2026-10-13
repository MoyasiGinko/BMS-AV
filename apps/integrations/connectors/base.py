"""Base connector interface and result primitives for external integrations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apps.integrations.models import IntegrationConnection


@dataclass
class ConnectorResult:
    """Standard execution result returned by all connector operations."""

    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    records_processed: int = 0
    records_succeeded: int = 0
    records_failed: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


class BaseConnector(ABC):
    """Abstract base class for all pluggable integration connectors."""

    connector_type: str
    name: str
    description: str
    category: str = "general"
    supported_actions: list[str] = []
    config_schema: list[dict[str, Any]] = []

    @abstractmethod
    def test_connection(self, connection: IntegrationConnection) -> ConnectorResult:
        """Validate connection credentials and endpoint reachability."""
        raise NotImplementedError

    def sync(
        self,
        connection: IntegrationConnection,
        direction: str = "inbound",
        params: dict[str, Any] | None = None,
    ) -> ConnectorResult:
        """Perform a bi-directional or directional synchronization cycle."""
        return ConnectorResult(
            success=True,
            message="Synchronization completed with no-op.",
            records_processed=0,
            records_succeeded=0,
            records_failed=0,
        )

    def execute_action(
        self,
        connection: IntegrationConnection,
        action: str,
        payload: dict[str, Any] | None = None,
    ) -> ConnectorResult:
        """Execute a discrete named connector action (e.g. charge, send_sms, webhook)."""
        if action not in self.supported_actions:
            return ConnectorResult(
                success=False,
                message=f"Action '{action}' is not supported by connector {self.connector_type}.",
                errors=[{"action": f"Unsupported action: {action}"}],
            )
        handler = getattr(self, f"action_{action}", None)
        if callable(handler):
            return handler(connection, payload or {})
        return ConnectorResult(
            success=False,
            message=f"Action handler for '{action}' not implemented.",
        )
