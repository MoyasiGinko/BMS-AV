"""Deployment mode detection and system initialization helpers.

Supports:
- "dedicated": Single-business deployment. Billing restrictions bypassed,
  primary organization auto-bound, organization switcher and public signups hidden.
- "saas": Multi-tenant platform deployment. Plans, quotas, read-only subscription
  lockdowns, and tenant selection enabled.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.apps import apps
from django.conf import settings

if TYPE_CHECKING:
    from apps.core.models import SystemConfiguration
    from apps.tenancy.models import Organization

logger = logging.getLogger(__name__)


def _get_system_configuration_model() -> type[SystemConfiguration] | None:
    try:
        return apps.get_model("core", "SystemConfiguration")
    except (LookupError, RuntimeError):
        return None


def _get_organization_model() -> type[Organization] | None:
    try:
        return apps.get_model("tenancy", "Organization")
    except (LookupError, RuntimeError):
        return None


def get_deployment_mode() -> str:
    """Return active deployment mode ('dedicated' or 'saas').

    Precedence:
    1. settings.DEPLOYMENT_MODE (if explicitly set via environment)
    2. SystemConfiguration.deployment_mode in database
    3. Default: 'dedicated'
    """
    env_mode = getattr(settings, "DEPLOYMENT_MODE", None)
    if env_mode:
        clean = str(env_mode).strip().lower()
        if clean in ("dedicated", "saas"):
            return clean

    model = _get_system_configuration_model()
    if model is not None:
        try:
            config = model.objects.filter(pk=1).first()
            if config and config.deployment_mode:
                return config.deployment_mode
        except Exception:
            logger.debug("SystemConfiguration table not queryable for deployment_mode.")

    return "dedicated"


def is_dedicated_mode() -> bool:
    """Return True if running as a standalone single business (dedicated mode)."""
    return get_deployment_mode() == "dedicated"


def is_saas_mode() -> bool:
    """Return True if running as a multi-tenant SaaS platform."""
    return get_deployment_mode() == "saas"


def is_system_initialized() -> bool:
    """Check if the system setup has been completed.

    Returns True if:
    1. SystemConfiguration has is_initialized=True.
    2. Or legacy/existing data already has at least one Organization.
    Returns False only on fresh, uninitialized deployments.
    """
    config_model = _get_system_configuration_model()
    org_model = _get_organization_model()

    if config_model is None or org_model is None:
        return True

    try:
        config = config_model.objects.filter(pk=1).first()
        if config is not None:
            if config.is_initialized:
                return True
            if not org_model.objects.exists():
                return False

        first_org = org_model.objects.filter(is_active=True).first()
        if first_org is not None:
            mode = getattr(settings, "DEPLOYMENT_MODE", "dedicated") or "dedicated"
            config_model.objects.get_or_create(
                pk=1,
                defaults={
                    "deployment_mode": str(mode).strip().lower(),
                    "is_initialized": True,
                    "system_name": first_org.name,
                    "primary_organization": first_org,
                },
            )
            return True

        return False
    except Exception:
        logger.debug("Database not yet initialized for system setup check.")
        return True


def get_primary_organization() -> Organization | None:
    """Return the primary organization for dedicated single-business mode."""
    if not is_dedicated_mode():
        return None

    config_model = _get_system_configuration_model()
    org_model = _get_organization_model()

    if config_model is None or org_model is None:
        return None

    try:
        config = config_model.objects.filter(pk=1).first()
        if config and config.primary_organization_id:
            return config.primary_organization

        return org_model.objects.filter(is_active=True).first()
    except Exception:
        logger.debug("Failed to retrieve primary organization in dedicated mode.")
        return None
