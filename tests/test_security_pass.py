"""Empirical security pass test suite for Business OS.

Validates:
1. Content Security Policy (CSP) and HTTP security headers.
2. Structured log sanitization (no passwords, tokens, API keys, or credentials).
3. Field-level symmetric encryption round-trip and masking.
4. Tenant plan-tier API rate limiting and web authentication rate limits.
5. Production deployment posture (check --deploy).
6. Cross-tenant model scoping and RLS invariants.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from typing import Any

import pytest
from django.conf import settings
from django.test import Client, RequestFactory

from apps.accounts.models import User
from apps.billing.models import Plan, Subscription
from apps.billing.services import resolve_org_plan_rate_limit
from apps.core.api.throttling import ApiKeyRateThrottle, TenantUserRateThrottle
from apps.core.crypto import decrypt_value, encrypt_value, mask_sensitive_value
from apps.core.logging import JSONLogFormatter, _sanitize_log_data
from apps.core.models import ApiKey
from apps.core.services import create_api_key
from apps.core.tenant_context import tenant_context
from apps.tenancy.models import Organization


@pytest.fixture
def org_and_user(db: Any) -> tuple[Organization, User]:
    user = User.objects.create_user(email="security_test@example.com", password="SecurePassword123!")
    org = Organization.objects.create(name="Security Corp", slug="security-corp")
    return org, user


# =========================================================================
# 1. Content Security Policy (CSP) and Security Headers Tests
# =========================================================================


@pytest.mark.django_db
def test_csp_and_security_headers_present_on_web_responses(client: Client) -> None:
    """Verify built-in ContentSecurityPolicyMiddleware and SecurityHeadersMiddleware
    attach required headers.
    """
    response = client.get("/accounts/login/")
    assert response.status_code == 200

    # 1. Content-Security-Policy header
    assert "Content-Security-Policy" in response.headers
    csp = response.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    assert "base-uri 'self'" in csp
    assert "form-action 'self'" in csp

    # 2. Additional HTTP security headers
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "Permissions-Policy" in response.headers
    perms = response.headers["Permissions-Policy"]
    assert "camera=()" in perms
    assert "microphone=()" in perms
    assert "payment=()" in perms


@pytest.mark.django_db
def test_csp_headers_present_on_api_responses(client: Client) -> None:
    """Verify CSP headers are attached to public API and health check responses."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert "Content-Security-Policy" in response.headers
    csp = response.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp


# =========================================================================
# 2. Secrets Handling & Structured Logging Sanitization Tests
# =========================================================================


def test_sanitize_log_data_redacts_sensitive_keys() -> None:
    """Verify _sanitize_log_data recursively scrubs passwords, tokens, API keys, credentials, and PII."""
    raw_payload = {
        "user_email": "admin@example.com",
        "password": "SuperSecretPassword!",
        "api_key": "bos_live_abcdef123456",
        "nested": {
            "auth_token": "bearer-jwt-token-xyz",
            "client_secret": "oauth-client-secret-999",
            "bank_account": "1234567890",
            "national_id": "987-65-4321",
            "regular_field": "keep-this-intact",
        },
        "item_list": [
            {"access_token": "token-in-list", "name": "Item A"},
            {"public_info": "safe"},
        ],
    }

    sanitized = _sanitize_log_data(raw_payload)

    assert sanitized["user_email"] == "admin@example.com"
    assert sanitized["password"] == "***REDACTED***"
    assert sanitized["api_key"] == "***REDACTED***"
    assert sanitized["nested"]["auth_token"] == "***REDACTED***"
    assert sanitized["nested"]["client_secret"] == "***REDACTED***"
    assert sanitized["nested"]["bank_account"] == "***REDACTED***"
    assert sanitized["nested"]["national_id"] == "***REDACTED***"
    assert sanitized["nested"]["regular_field"] == "keep-this-intact"
    assert sanitized["item_list"][0]["access_token"] == "***REDACTED***"
    assert sanitized["item_list"][0]["name"] == "Item A"
    assert sanitized["item_list"][1]["public_info"] == "safe"


def test_json_log_formatter_masks_extras() -> None:
    """Verify JSONLogFormatter outputs valid JSON and redacts sensitive data passed via logger extras."""
    formatter = JSONLogFormatter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=100,
        msg="API authentication event",
        args=(),
        exc_info=None,
    )
    record.api_key = "bos_live_sensitive12345"  # type: ignore[attr-defined]
    record.password = "PlaintextPassword!"  # type: ignore[attr-defined]
    record.client_ip = "192.168.1.1"  # type: ignore[attr-defined]

    formatted_str = formatter.format(record)
    parsed = json.loads(formatted_str)

    assert parsed["message"] == "API authentication event"
    assert parsed["extra"]["api_key"] == "***REDACTED***"
    assert parsed["extra"]["password"] == "***REDACTED***"
    assert parsed["extra"]["client_ip"] == "192.168.1.1"


def test_symmetric_field_encryption_roundtrip() -> None:
    """Verify Fernet-based field encryption encrypts to ciphertext and decrypts to original plaintext."""
    plaintext = "Sensitive-Bank-IBAN-DE89370400440532013000"
    ciphertext = encrypt_value(plaintext)

    assert ciphertext != plaintext
    assert isinstance(ciphertext, str)
    assert len(ciphertext) > 50

    decrypted = decrypt_value(ciphertext)
    assert decrypted == plaintext


def test_symmetric_field_encryption_invalid_token_handling() -> None:
    """Verify decrypt_value gracefully returns empty string on malformed tokens without throwing."""
    assert decrypt_value("not-a-valid-fernet-token") == ""
    assert decrypt_value(None) == ""
    assert decrypt_value("") == ""


def test_mask_sensitive_value_behavior() -> None:
    """Verify mask_sensitive_value shows only the designated trailing characters."""
    assert mask_sensitive_value("1234567890", visible_tail=4) == "******7890"
    assert mask_sensitive_value("123", visible_tail=4) == "***"
    assert mask_sensitive_value("") == ""
    assert mask_sensitive_value(None) == ""


# =========================================================================
# 3. Multi-Tier Rate Limiting Tests (API & Web)
# =========================================================================


@pytest.mark.django_db
def test_api_rate_limit_dynamic_resolution_by_plan(org_and_user: tuple[Organization, User]) -> None:
    """Verify resolve_org_plan_rate_limit scales dynamically with tenant subscription tier."""
    org, _ = org_and_user

    # Default without plan
    assert resolve_org_plan_rate_limit(org) == "60/minute"

    # Starter plan
    starter_plan = Plan.objects.create(name="Starter", slug="starter", price_monthly=29)
    sub = Subscription.all_tenants.create(organization=org, plan=starter_plan, status="active")
    assert resolve_org_plan_rate_limit(org) == "60/minute"

    # Growth plan
    growth_plan = Plan.objects.create(name="Growth", slug="growth", price_monthly=79)
    sub.plan = growth_plan
    sub.save(update_fields=["plan"])
    assert resolve_org_plan_rate_limit(org) == "300/minute"

    # Business plan
    biz_plan = Plan.objects.create(name="Business", slug="business", price_monthly=199)
    sub.plan = biz_plan
    sub.save(update_fields=["plan"])
    assert resolve_org_plan_rate_limit(org) == "1000/minute"

    # Enterprise plan
    ent_plan = Plan.objects.create(name="Enterprise", slug="enterprise", price_monthly=499)
    sub.plan = ent_plan
    sub.save(update_fields=["plan"])
    assert resolve_org_plan_rate_limit(org) == "3000/minute"


@pytest.mark.django_db
def test_tenant_user_throttle_defers_to_api_key_throttle(org_and_user: tuple[Organization, User]) -> None:
    """Verify TenantUserRateThrottle ignores API Key requests so ApiKeyRateThrottle manages rate limiting."""
    org, user = org_and_user
    api_key, _ = create_api_key(
        organization=org,
        name="Test API Key",
        user=user,
        actor=user,
    )

    throttle = TenantUserRateThrottle()
    factory = RequestFactory()

    # Regular session request
    request = factory.get("/api/v1/customers/")
    request.user = user
    request.auth = None
    request.organization = org
    assert throttle.get_cache_key(request, None) is not None

    # Request with API Key auth: TenantUserRateThrottle returns None (deferring to ApiKeyRateThrottle)
    request.auth = api_key
    assert throttle.get_cache_key(request, None) is None

    # ApiKeyRateThrottle handles the request
    key_throttle = ApiKeyRateThrottle()
    key_cache_key = key_throttle.get_cache_key(request, None)
    assert key_cache_key is not None
    assert api_key.prefix in key_cache_key


def test_account_rate_limits_configured_in_settings() -> None:
    """Verify allauth brute-force protection rate limits are explicitly configured in Django settings."""
    rate_limits = getattr(settings, "ACCOUNT_RATE_LIMITS", None)
    assert rate_limits is not None
    assert "login" in rate_limits
    assert "login_failed" in rate_limits
    assert "signup" in rate_limits
    assert "reset_password" in rate_limits


# =========================================================================
# 4. Production Deployment & Dependency Security Verification
# =========================================================================


def test_production_deployment_check_clean() -> None:
    """Verify check --deploy runs clean against prod_check settings without any WARNING or ERROR."""
    cmd = [
        sys.executable,
        "manage.py",
        "check",
        "--deploy",
        "--settings=config.settings.prod_check",
        "--fail-level=WARNING",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"check --deploy failed:\n{proc.stdout}\n{proc.stderr}"
    assert "System check identified no issues" in (proc.stdout + proc.stderr)


def test_pip_audit_vulnerability_scan() -> None:
    """Verify pip-audit reports 0 known vulnerabilities across project dependencies."""
    cmd = [sys.executable, "-m", "pip_audit", "--progress-spinner=off"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"pip-audit found vulnerabilities or failed:\n{combined}"
    assert "No known vulnerabilities found" in combined


# =========================================================================
# 5. Cross-Tenant Model Scoping and Cryptographic API Key Verification
# =========================================================================


@pytest.mark.django_db
def test_api_key_hashes_are_irreversible_and_tenant_isolated() -> None:
    """Verify API keys store irreversible hashes, raw secret is only returned once,
    and tenant isolation holds.
    """
    user = User.objects.create_user(email="key_tester@example.com", password="Password123!")
    org_a = Organization.objects.create(name="Alpha Corp", slug="alpha-corp")
    org_b = Organization.objects.create(name="Beta Corp", slug="beta-corp")

    api_key_a, raw_secret_a = create_api_key(
        organization=org_a,
        name="Alpha Key",
        user=user,
        actor=user,
    )

    # 1. Raw secret is not stored on the model instance (irreversible SHA-256 hash)
    assert raw_secret_a not in api_key_a.key_hash
    assert len(api_key_a.key_hash) == 64

    # 2. Key verification works via check_password
    assert api_key_a.verify_key(raw_secret_a) is True
    assert api_key_a.verify_key("wrong_secret_value") is False

    # 3. Tenant isolation via TenantManager
    with tenant_context(org_a):
        assert ApiKey.objects.filter(pk=api_key_a.pk).exists() is True

    with tenant_context(org_b):
        assert ApiKey.objects.filter(pk=api_key_a.pk).exists() is False
