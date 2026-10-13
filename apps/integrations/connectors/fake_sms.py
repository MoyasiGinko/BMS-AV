"""Sandbox SMS communications gateway connector."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, ClassVar

from apps.integrations.connectors.base import BaseConnector, ConnectorResult

if TYPE_CHECKING:
    from apps.integrations.models import IntegrationConnection


class FakeSmsConnector(BaseConnector):
    """Sandbox SMS gateway for simulated OTPs, customer dispatch alerts, and reminders."""

    connector_type = "fake_sms"
    name = "Sandbox SMS Provider"
    description = "Mock SMS gateway provider with in-memory outbox verification."
    category = "messaging"
    supported_actions = ["send_sms", "get_delivery_status", "clear_outbox"]
    config_schema = [
        {
            "name": "sender_id",
            "label": "Sender ID / From Number",
            "type": "text",
            "default": "+15550199",
            "required": True,
            "help_text": "Alpha sender ID or phone number.",
        },
        {
            "name": "rate_limit_per_minute",
            "label": "Rate Limit (msgs/min)",
            "type": "number",
            "default": 60,
            "required": False,
        },
    ]

    # In-memory test inspection outbox
    outbox: ClassVar[list[dict[str, Any]]] = []

    @classmethod
    def clear_outbox(cls) -> None:
        """Clear recorded SMS messages."""
        cls.outbox.clear()

    def test_connection(self, connection: IntegrationConnection) -> ConnectorResult:
        """Validate API credentials."""
        creds = connection.credentials
        account_sid = creds.get("account_sid") or creds.get("api_key")
        auth_token = creds.get("auth_token") or creds.get("api_secret")

        if not account_sid or not auth_token:
            return ConnectorResult(
                success=False,
                message="Account SID and Auth Token are required in credentials.",
                errors=[{"auth": "Missing Account SID or Auth Token"}],
            )

        if (connection.config or {}).get("simulate_error"):
            return ConnectorResult(
                success=False,
                message="SMS Provider returned 401 Unauthorized.",
                errors=[{"auth": "Invalid authentication token"}],
            )

        return ConnectorResult(
            success=True,
            message="Sandbox SMS Gateway is online and ready.",
            data={"sender_id": (connection.config or {}).get("sender_id", "+15550199")},
        )

    def action_send_sms(
        self,
        connection: IntegrationConnection,
        payload: dict[str, Any],
    ) -> ConnectorResult:
        """Send simulated SMS message."""
        recipient = payload.get("to") or payload.get("phone")
        message = payload.get("message") or payload.get("text") or ""

        if not recipient:
            return ConnectorResult(
                success=False,
                message="Destination phone number ('to') is required.",
                errors=[{"to": "Missing recipient"}],
            )

        msg_id = f"sms_{uuid.uuid4().hex[:12]}"
        sender_id = (connection.config or {}).get("sender_id", "+15550199")
        entry = {
            "id": msg_id,
            "from": sender_id,
            "to": recipient,
            "message": message,
            "connection_id": str(connection.public_id),
            "status": "delivered",
        }
        self.outbox.append(entry)

        return ConnectorResult(
            success=True,
            message=f"SMS message {msg_id} delivered to {recipient}.",
            records_processed=1,
            records_succeeded=1,
            data=entry,
        )

    def action_get_delivery_status(
        self,
        connection: IntegrationConnection,
        payload: dict[str, Any],
    ) -> ConnectorResult:
        """Inspect delivery status of an SMS message."""
        msg_id = payload.get("message_id")
        match = next((m for m in self.outbox if m["id"] == msg_id), None)
        if not match:
            return ConnectorResult(
                success=False,
                message=f"Message ID {msg_id} not found in SMS delivery ledger.",
            )
        return ConnectorResult(
            success=True,
            message=f"Message {msg_id} status: {match['status']}",
            data=match,
        )

    def action_clear_outbox(
        self,
        connection: IntegrationConnection,
        payload: dict[str, Any],
    ) -> ConnectorResult:
        """Clear test outbox."""
        self.clear_outbox()
        return ConnectorResult(success=True, message="SMS outbox cleared.")
