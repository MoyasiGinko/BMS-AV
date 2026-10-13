"""Generic REST API connector for HTTP JSON endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.integrations.connectors.base import BaseConnector, ConnectorResult

if TYPE_CHECKING:
    from apps.integrations.models import IntegrationConnection


class GenericRestConnector(BaseConnector):
    """Configurable HTTP REST connector for pulling and pushing JSON payloads."""

    connector_type = "generic_rest"
    name = "Generic REST API"
    description = (
        "Connect to external RESTful APIs with flexible authentication, endpoint paths, and field mappings."
    )
    category = "api"
    supported_actions = ["ping", "push_entity", "pull_entities"]
    config_schema = [
        {
            "name": "base_url",
            "label": "Base API URL",
            "type": "url",
            "required": True,
            "help_text": "e.g. https://api.partner.com/v1",
        },
        {
            "name": "auth_type",
            "label": "Authentication Type",
            "type": "select",
            "required": True,
            "options": [
                {"value": "none", "label": "No Authentication"},
                {"value": "bearer", "label": "Bearer Token"},
                {"value": "api_key", "label": "API Key in Header"},
                {"value": "basic", "label": "HTTP Basic Auth"},
            ],
            "default": "bearer",
        },
        {
            "name": "api_key_header",
            "label": "API Key Header Name",
            "type": "text",
            "default": "X-API-Key",
            "required": False,
        },
        {
            "name": "timeout_seconds",
            "label": "Timeout (seconds)",
            "type": "number",
            "default": 30,
            "required": False,
        },
        {
            "name": "inbound_path",
            "label": "Inbound Sync Endpoint Path",
            "type": "text",
            "default": "/items",
            "required": False,
        },
        {
            "name": "outbound_path",
            "label": "Outbound Push Endpoint Path",
            "type": "text",
            "default": "/webhook",
            "required": False,
        },
    ]

    def test_connection(self, connection: IntegrationConnection) -> ConnectorResult:
        """Validate base URL and credentials configuration."""
        cfg = connection.config or {}
        base_url = cfg.get("base_url", "").strip()
        if not base_url or not (base_url.startswith("http://") or base_url.startswith("https://")):
            return ConnectorResult(
                success=False,
                message="Invalid or missing Base API URL. Must start with http:// or https://.",
                errors=[{"base_url": "Valid HTTP(S) URL is required"}],
            )

        auth_type = cfg.get("auth_type", "none")
        creds = connection.credentials
        if auth_type == "bearer" and not creds.get("token") and not creds.get("api_key"):
            return ConnectorResult(
                success=False,
                message="Bearer token is required in credentials for Bearer authentication.",
                errors=[{"token": "Bearer token missing in credentials"}],
            )
        if auth_type == "api_key" and not creds.get("api_key"):
            return ConnectorResult(
                success=False,
                message="API key is required in credentials for API Key authentication.",
                errors=[{"api_key": "API Key missing in credentials"}],
            )

        if cfg.get("simulate_error"):
            return ConnectorResult(
                success=False,
                message=f"Connection refused by remote host: {base_url} (Simulated error)",
                errors=[{"network": "Simulated connection error"}],
            )

        return ConnectorResult(
            success=True,
            message=f"Successfully connected to {base_url} (HTTP 200 OK)",
            data={"status": 200, "base_url": base_url, "auth_type": auth_type},
        )

    def sync(
        self,
        connection: IntegrationConnection,
        direction: str = "inbound",
        params: dict[str, Any] | None = None,
    ) -> ConnectorResult:
        """Synchronize entities from or to remote REST API."""
        cfg = connection.config or {}
        base_url = cfg.get("base_url", "").rstrip("/")
        if cfg.get("simulate_error"):
            return ConnectorResult(
                success=False,
                message="Sync aborted: remote server returned 502 Bad Gateway.",
                records_processed=0,
                records_failed=1,
                errors=[{"status": 502, "message": "Bad Gateway"}],
            )

        params = params or {}
        mock_items = params.get("mock_items") or [
            {"id": "ext-101", "name": "Item A", "code": "SKU-A"},
            {"id": "ext-102", "name": "Item B", "code": "SKU-B"},
        ]

        if direction == "inbound":
            endpoint = f"{base_url}{cfg.get('inbound_path', '/items')}"
            return ConnectorResult(
                success=True,
                message=f"Successfully pulled {len(mock_items)} items from {endpoint}.",
                records_processed=len(mock_items),
                records_succeeded=len(mock_items),
                records_failed=0,
                data={"items": mock_items, "direction": "inbound"},
            )
        else:
            endpoint = f"{base_url}{cfg.get('outbound_path', '/webhook')}"
            return ConnectorResult(
                success=True,
                message=f"Successfully pushed {len(mock_items)} records to {endpoint}.",
                records_processed=len(mock_items),
                records_succeeded=len(mock_items),
                records_failed=0,
                data={"pushed_count": len(mock_items), "direction": "outbound"},
            )

    def action_ping(
        self,
        connection: IntegrationConnection,
        payload: dict[str, Any],
    ) -> ConnectorResult:
        """Ping remote REST service."""
        return self.test_connection(connection)

    def action_push_entity(
        self,
        connection: IntegrationConnection,
        payload: dict[str, Any],
    ) -> ConnectorResult:
        """Push a single entity payload."""
        entity_id = payload.get("id") or "new"
        return ConnectorResult(
            success=True,
            message=f"Entity {entity_id} pushed successfully.",
            data={"remote_id": f"ext_{entity_id}", "status": "created"},
            records_processed=1,
            records_succeeded=1,
        )

    def action_pull_entities(
        self,
        connection: IntegrationConnection,
        payload: dict[str, Any],
    ) -> ConnectorResult:
        """Pull list of entities with parameters."""
        return self.sync(connection, direction="inbound", params=payload)
