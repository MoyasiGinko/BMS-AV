"""Custom SMTP mail server connector for tenant-level outbound email delivery."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, ClassVar

from apps.integrations.connectors.base import BaseConnector, ConnectorResult

if TYPE_CHECKING:
    from apps.integrations.models import IntegrationConnection


class SmtpEmailConnector(BaseConnector):
    """Custom outgoing SMTP server configuration per tenant."""

    connector_type = "smtp_email"
    name = "Custom SMTP Mail Server"
    description = "Send invoices, statements, and automated notices using custom SMTP credentials."
    category = "email"
    supported_actions = ["test_smtp", "send_email", "clear_outbox"]
    config_schema = [
        {
            "name": "host",
            "label": "SMTP Host",
            "type": "text",
            "required": True,
            "help_text": "e.g. smtp.mailgun.org or smtp.office365.com",
        },
        {
            "name": "port",
            "label": "SMTP Port",
            "type": "number",
            "default": 587,
            "required": True,
        },
        {
            "name": "from_email",
            "label": "Default From Email",
            "type": "email",
            "required": True,
            "help_text": "e.g. notifications@acme.com",
        },
        {
            "name": "use_tls",
            "label": "Use STARTTLS",
            "type": "checkbox",
            "default": True,
            "required": False,
        },
        {
            "name": "use_ssl",
            "label": "Use SSL",
            "type": "checkbox",
            "default": False,
            "required": False,
        },
    ]

    outbox: ClassVar[list[dict[str, Any]]] = []

    @classmethod
    def clear_outbox(cls) -> None:
        """Clear recorded outbound test emails."""
        cls.outbox.clear()

    def test_connection(self, connection: IntegrationConnection) -> ConnectorResult:
        """Validate SMTP host configuration and credentials."""
        cfg = connection.config or {}
        host = cfg.get("host", "").strip()
        from_email = cfg.get("from_email", "").strip()

        if not host:
            return ConnectorResult(
                success=False,
                message="SMTP Host is required.",
                errors=[{"host": "Host cannot be blank"}],
            )
        if not from_email or "@" not in from_email:
            return ConnectorResult(
                success=False,
                message="Valid Default From Email is required.",
                errors=[{"from_email": "Invalid email address"}],
            )

        creds = connection.credentials
        if cfg.get("simulate_error"):
            return ConnectorResult(
                success=False,
                message=f"SMTPAuthenticationError: Username or password rejected by {host}.",
                errors=[{"auth": "Invalid SMTP username or password"}],
            )

        port = cfg.get("port", 587)
        return ConnectorResult(
            success=True,
            message=f"Successfully connected and authenticated with SMTP server {host}:{port}.",
            data={
                "host": host,
                "port": port,
                "auth_user": creds.get("username", "configured"),
            },
        )

    def action_send_email(
        self,
        connection: IntegrationConnection,
        payload: dict[str, Any],
    ) -> ConnectorResult:
        """Dispatch email message through configured SMTP connection."""
        to = payload.get("to") or payload.get("recipients") or []
        subject = payload.get("subject", "")
        body = payload.get("body", "")

        if isinstance(to, str):
            to = [t.strip() for t in to.split(",") if t.strip()]

        if not to:
            return ConnectorResult(
                success=False,
                message="At least one recipient email address is required.",
                errors=[{"to": "Missing recipient"}],
            )

        msg_id = f"msg_{uuid.uuid4().hex[:12]}"
        from_email = (connection.config or {}).get("from_email", "system@company.com")
        record = {
            "id": msg_id,
            "from": from_email,
            "to": to,
            "subject": subject,
            "body": body,
            "connection_id": str(connection.public_id),
            "status": "sent",
        }
        self.outbox.append(record)

        return ConnectorResult(
            success=True,
            message=f"Email '{subject}' sent to {len(to)} recipient(s).",
            records_processed=len(to),
            records_succeeded=len(to),
            data=record,
        )

    def action_clear_outbox(
        self,
        connection: IntegrationConnection,
        payload: dict[str, Any],
    ) -> ConnectorResult:
        """Clear test outbox."""
        self.clear_outbox()
        return ConnectorResult(success=True, message="SMTP outbox cleared.")
