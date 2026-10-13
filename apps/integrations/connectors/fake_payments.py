"""Sandbox payments gateway connector for payment charges, refunds, and verifications."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from apps.integrations.connectors.base import BaseConnector, ConnectorResult

if TYPE_CHECKING:
    from apps.integrations.models import IntegrationConnection


class FakePaymentsConnector(BaseConnector):
    """Sandbox payment processor for test checkout, invoice payments, and automated refunds."""

    connector_type = "fake_payments"
    name = "Sandbox Payments Gateway"
    description = "Test payment processor simulating charge authorizations, captures, and refunds."
    category = "payments"
    supported_actions = ["charge", "refund", "verify_payment"]
    config_schema = [
        {
            "name": "environment",
            "label": "Environment Mode",
            "type": "select",
            "required": True,
            "options": [
                {"value": "sandbox", "label": "Sandbox / Simulation"},
                {"value": "testing", "label": "Integration Test Mode"},
            ],
            "default": "sandbox",
        },
        {
            "name": "currency",
            "label": "Settlement Currency",
            "type": "text",
            "default": "USD",
            "required": True,
        },
        {
            "name": "auto_capture",
            "label": "Auto-Capture Charges",
            "type": "checkbox",
            "default": True,
            "required": False,
        },
    ]

    def test_connection(self, connection: IntegrationConnection) -> ConnectorResult:
        """Verify merchant ID and sandbox API key."""
        creds = connection.credentials
        api_key = creds.get("api_key") or creds.get("secret_key")
        merchant_id = creds.get("merchant_id") or (connection.config or {}).get("merchant_id")

        if not api_key:
            return ConnectorResult(
                success=False,
                message="Sandbox API Key is required in connection credentials.",
                errors=[{"api_key": "Missing sandbox API key"}],
            )

        if (connection.config or {}).get("simulate_error"):
            return ConnectorResult(
                success=False,
                message="Authentication failed: Invalid sandbox API key or merchant ID.",
                errors=[{"auth": "Invalid credentials"}],
            )

        return ConnectorResult(
            success=True,
            message="Successfully authenticated with Sandbox Payments Gateway.",
            data={"merchant_id": merchant_id or "mch_sandbox_demo", "status": "active"},
        )

    def sync(
        self,
        connection: IntegrationConnection,
        direction: str = "inbound",
        params: dict[str, Any] | None = None,
    ) -> ConnectorResult:
        """Fetch settlement batch transaction reports."""
        return ConnectorResult(
            success=True,
            message="Fetched recent sandbox settlement batch (0 disputed items).",
            records_processed=5,
            records_succeeded=5,
            records_failed=0,
            data={"batch_id": f"batch_{uuid.uuid4().hex[:8]}", "total_settled": "1250.00"},
        )

    def action_charge(
        self,
        connection: IntegrationConnection,
        payload: dict[str, Any],
    ) -> ConnectorResult:
        """Process a simulated payment charge."""
        amount = Decimal(str(payload.get("amount", "100.00")))
        currency = payload.get("currency") or (connection.config or {}).get("currency", "USD")
        reference_id = payload.get("reference_id") or f"ref_{uuid.uuid4().hex[:8]}"

        if (connection.config or {}).get("simulate_decline") or payload.get("simulate_decline"):
            return ConnectorResult(
                success=False,
                message="Card declined by issuer: Insufficient funds (Simulated).",
                errors=[{"code": "card_declined", "decline_reason": "insufficient_funds"}],
            )

        txn_id = f"txn_sb_{uuid.uuid4().hex[:12]}"
        return ConnectorResult(
            success=True,
            message=f"Charge of {amount} {currency} approved.",
            records_processed=1,
            records_succeeded=1,
            data={
                "transaction_id": txn_id,
                "amount": str(amount),
                "currency": currency,
                "reference_id": reference_id,
                "status": "succeeded",
            },
        )

    def action_refund(
        self,
        connection: IntegrationConnection,
        payload: dict[str, Any],
    ) -> ConnectorResult:
        """Process a simulated refund."""
        txn_id = payload.get("transaction_id")
        if not txn_id:
            return ConnectorResult(
                success=False,
                message="Transaction ID is required to process refund.",
                errors=[{"transaction_id": "Missing transaction_id"}],
            )

        refund_id = f"ref_sb_{uuid.uuid4().hex[:12]}"
        return ConnectorResult(
            success=True,
            message=f"Refund {refund_id} for transaction {txn_id} succeeded.",
            records_processed=1,
            records_succeeded=1,
            data={
                "refund_id": refund_id,
                "original_transaction_id": txn_id,
                "status": "refunded",
            },
        )

    def action_verify_payment(
        self,
        connection: IntegrationConnection,
        payload: dict[str, Any],
    ) -> ConnectorResult:
        """Verify transaction status."""
        txn_id = payload.get("transaction_id", "txn_sb_demo")
        return ConnectorResult(
            success=True,
            message=f"Transaction {txn_id} verified as settled.",
            data={"transaction_id": txn_id, "status": "settled"},
            records_processed=1,
            records_succeeded=1,
        )
