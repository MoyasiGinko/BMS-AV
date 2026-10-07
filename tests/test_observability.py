"""Tests for Observability foundation (P0-11):

- Structured JSON logging with request/org/user IDs.
- Observability context binding via contextvars.
- Sentry hook enrichment and env gating.
- Security headers middleware.
- Deploy check on prod_check settings.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from unittest.mock import MagicMock, patch

from django.test import RequestFactory
from django.test.utils import override_settings

from apps.core.logging import JSONLogFormatter, add_observability_context
from apps.core.middleware import RequestIdMiddleware, SecurityHeadersMiddleware
from apps.core.sentry import _before_send, init_sentry
from apps.core.tenant_context import (
    get_current_request_id,
    set_current_organization,
    set_current_request_id,
    set_current_user_id,
)


class TestStructuredLogging:
    def test_json_formatter_basic_record(self) -> None:
        formatter = JSONLogFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="User %s logged in",
            args=("admin",),
            exc_info=None,
        )

        formatted = formatter.format(record)
        data = json.loads(formatted)

        assert data["level"] == "INFO"
        assert data["logger"] == "test.logger"
        assert data["message"] == "User admin logged in"
        assert "timestamp" in data
        assert data["request_id"] is None
        assert data["organization_id"] is None
        assert data["user_id"] is None

    def test_json_formatter_with_contextvars_and_extras(self) -> None:
        formatter = JSONLogFormatter()

        # Set ambient context
        set_current_request_id("req-uuid-test-123")
        set_current_user_id(42)
        mock_org = MagicMock(pk=7)
        set_current_organization(mock_org)

        try:
            record = logging.LogRecord(
                name="apps.core.services",
                level=logging.WARNING,
                pathname="services.py",
                lineno=100,
                msg="Stock low for sku %s",
                args=("SKU-001",),
                exc_info=None,
            )
            record.custom_field = "custom_value"  # type: ignore[attr-defined]

            formatted = formatter.format(record)
            data = json.loads(formatted)

            assert data["level"] == "WARNING"
            assert data["request_id"] == "req-uuid-test-123"
            assert data["organization_id"] == 7
            assert data["user_id"] == 42
            assert data["extra"]["custom_field"] == "custom_value"
        finally:
            set_current_request_id(None)
            set_current_user_id(None)
            set_current_organization(None)

    def test_json_formatter_with_exception(self) -> None:
        formatter = JSONLogFormatter()
        try:
            raise ValueError("Something broke")
        except ValueError:
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="apps.core.errors",
            level=logging.ERROR,
            pathname="errors.py",
            lineno=50,
            msg="Operation failed",
            args=(),
            exc_info=exc_info,
        )

        formatted = formatter.format(record)
        data = json.loads(formatted)
        assert data["level"] == "ERROR"
        assert "ValueError: Something broke" in data["exception"]

    def test_structlog_processor(self) -> None:
        set_current_request_id("structlog-req-1")
        set_current_user_id(10)
        mock_org = MagicMock(pk=3)
        set_current_organization(mock_org)

        try:
            event_dict = {"event": "payment_processed", "amount": 100}
            enriched = add_observability_context(None, "info", event_dict)

            assert enriched["request_id"] == "structlog-req-1"
            assert enriched["user_id"] == 10
            assert enriched["organization_id"] == 3
            assert enriched["amount"] == 100
        finally:
            set_current_request_id(None)
            set_current_user_id(None)
            set_current_organization(None)


class TestSecurityHeadersAndMiddleware:
    def test_security_headers_middleware(self) -> None:
        rf = RequestFactory()
        request = rf.get("/healthz")

        def mock_response(req: object) -> MagicMock:
            res = MagicMock()
            res.headers = {}
            res.setdefault = res.headers.setdefault
            return res

        middleware = SecurityHeadersMiddleware(mock_response)
        response = middleware(request)

        assert "Permissions-Policy" in response.headers
        assert "camera=()" in response.headers["Permissions-Policy"]
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"

    def test_request_id_middleware_sets_contextvar(self) -> None:
        rf = RequestFactory()
        request = rf.get("/healthz", HTTP_X_REQUEST_ID="trace-req-xyz")

        captured_context_id = None

        def verify_context(req: object) -> MagicMock:
            nonlocal captured_context_id
            captured_context_id = get_current_request_id()
            res = MagicMock()
            res.__setitem__ = MagicMock()
            return res

        middleware = RequestIdMiddleware(verify_context)
        middleware(request)

        assert captured_context_id == "trace-req-xyz"


class TestSentryIntegration:
    def test_init_sentry_env_gated_false(self) -> None:
        with override_settings(SENTRY_DSN=""):
            assert init_sentry() is False

    @patch("sentry_sdk.init")
    def test_init_sentry_env_gated_true(self, mock_sentry_init: MagicMock) -> None:
        with override_settings(SENTRY_DSN="https://key@sentry.io/123", ENVIRONMENT="staging"):
            assert init_sentry() is True
            mock_sentry_init.assert_called_once()

    def test_before_send_enriches_event(self) -> None:
        set_current_request_id("sentry-req-99")
        set_current_user_id(5)
        mock_org = MagicMock(pk=2)
        set_current_organization(mock_org)

        try:
            event: dict[str, object] = {"message": "Database timeout"}
            enriched = _before_send(event, {})  # type: ignore[arg-type]

            tags = enriched["tags"]  # type: ignore[index]
            assert tags["request_id"] == "sentry-req-99"
            assert tags["organization_id"] == "2"
            user = enriched["user"]  # type: ignore[index]
            assert user["id"] == "5"
        finally:
            set_current_request_id(None)
            set_current_user_id(None)
            set_current_organization(None)


def test_deploy_check_clean() -> None:
    """Validate check --deploy runs clean on prod_check settings."""
    result = subprocess.run(
        [
            sys.executable,
            "manage.py",
            "check",
            "--deploy",
            "--settings=config.settings.prod_check",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    combined = f"{result.stdout}\n{result.stderr}"
    assert "System check identified no issues" in combined
