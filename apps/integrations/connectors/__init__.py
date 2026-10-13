"""Integration connector framework and registered connectors."""

from __future__ import annotations

from apps.integrations.connectors.base import BaseConnector, ConnectorResult
from apps.integrations.connectors.csv_import import CsvImportConnector
from apps.integrations.connectors.fake_payments import FakePaymentsConnector
from apps.integrations.connectors.fake_sms import FakeSmsConnector
from apps.integrations.connectors.generic_rest import GenericRestConnector
from apps.integrations.connectors.registry import ConnectorRegistry, connector_registry
from apps.integrations.connectors.smtp_email import SmtpEmailConnector
from apps.integrations.connectors.zapier_compat import ZapierCompatConnector

__all__ = [
    "BaseConnector",
    "ConnectorRegistry",
    "ConnectorResult",
    "CsvImportConnector",
    "FakePaymentsConnector",
    "FakeSmsConnector",
    "GenericRestConnector",
    "SmtpEmailConnector",
    "ZapierCompatConnector",
    "connector_registry",
]
