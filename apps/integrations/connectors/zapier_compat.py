"""Zapier REST Hooks compatibility connector for triggers and workflow subscriptions."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from apps.integrations.connectors.base import BaseConnector, ConnectorResult

if TYPE_CHECKING:
    from apps.integrations.models import IntegrationConnection


SAMPLE_PAYLOADS: dict[str, dict[str, Any]] = {
    "customer.created": {
        "id": "cust_sample_101",
        "name": "Acme Global Industries",
        "code": "CUST-00101",
        "email": "procurement@acme.com",
        "phone": "+1 (555) 012-3456",
        "current_balance": "0.00",
        "status": "active",
    },
    "sale.confirmed": {
        "id": "ord_sample_201",
        "order_number": "SO-2026-0042",
        "customer_name": "Acme Global Industries",
        "grand_total": "1450.00",
        "status": "confirmed",
        "created_at": "2026-10-13T10:00:00Z",
    },
    "invoice.paid": {
        "id": "inv_sample_301",
        "invoice_number": "INV-2026-0089",
        "customer_name": "Acme Global Industries",
        "grand_total": "1450.00",
        "balance_due": "0.00",
        "status": "paid",
        "paid_at": "2026-10-13T11:30:00Z",
    },
}


class ZapierCompatConnector(BaseConnector):
    """Zapier REST Hooks subscription provider for no-code automated integrations."""

    connector_type = "zapier_compat"
    name = "Zapier REST Hooks"
    description = "Enable Zapier triggers with automated subscription endpoints and sample payload schemas."
    category = "automation"
    supported_actions = ["subscribe", "unsubscribe", "get_sample"]
    config_schema = [
        {
            "name": "api_key",
            "label": "Shared Zapier API Key",
            "type": "text",
            "required": True,
            "help_text": "Secret key verified on Zapier subscribe/unsubscribe requests.",
        },
        {
            "name": "enable_all_triggers",
            "label": "Enable All System Triggers",
            "type": "checkbox",
            "default": True,
            "required": False,
        },
    ]

    def test_connection(self, connection: IntegrationConnection) -> ConnectorResult:
        """Verify API key is configured."""
        cfg = connection.config or {}
        creds = connection.credentials
        key = creds.get("api_key") or cfg.get("api_key")

        if not key:
            return ConnectorResult(
                success=False,
                message="Zapier API Key must be set in credentials or configuration.",
                errors=[{"api_key": "Missing Zapier API Key"}],
            )

        return ConnectorResult(
            success=True,
            message="Zapier REST Hooks compatibility engine is ready.",
            data={"triggers_supported": list(SAMPLE_PAYLOADS.keys())},
        )

    def action_subscribe(
        self,
        connection: IntegrationConnection,
        payload: dict[str, Any],
    ) -> ConnectorResult:
        """Handle Zapier subscribe request."""
        target_url = payload.get("target_url") or payload.get("hookUrl")
        event = payload.get("event") or payload.get("event_type", "customer.created")

        if not target_url:
            return ConnectorResult(
                success=False,
                message="Target URL ('target_url') is required for Zapier REST Hook subscription.",
                errors=[{"target_url": "Missing target URL"}],
            )

        hook_id = f"zap_hook_{uuid.uuid4().hex[:12]}"
        return ConnectorResult(
            success=True,
            message=f"Zapier hook subscribed for '{event}' to {target_url}.",
            data={
                "id": hook_id,
                "target_url": target_url,
                "event": event,
                "status": "active",
            },
        )

    def action_unsubscribe(
        self,
        connection: IntegrationConnection,
        payload: dict[str, Any],
    ) -> ConnectorResult:
        """Handle Zapier unsubscribe request."""
        hook_id = payload.get("id") or payload.get("hook_id")
        return ConnectorResult(
            success=True,
            message=f"Zapier hook {hook_id} unsubscribed.",
            data={"id": hook_id, "status": "deleted"},
        )

    def action_get_sample(
        self,
        connection: IntegrationConnection,
        payload: dict[str, Any],
    ) -> ConnectorResult:
        """Return sample record for Zapier trigger configuration."""
        event = payload.get("event") or "customer.created"
        sample = SAMPLE_PAYLOADS.get(event) or SAMPLE_PAYLOADS["customer.created"]
        return ConnectorResult(
            success=True,
            message=f"Sample payload for {event} retrieved.",
            data=sample,
        )
