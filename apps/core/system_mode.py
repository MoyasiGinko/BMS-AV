"""Deployment mode detection and system initialization helpers.

Supports:
- "dedicated": Single-business deployment. Billing restrictions bypassed,
  primary organization auto-bound, organization switcher and public signups hidden.
- "saas": Multi-tenant platform deployment. Plans, quotas, read-only subscription
  lockdowns, and tenant selection enabled.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from django.conf import settings

if TYPE_CHECKING:
    from apps.tenancy.models import Organization

logger = logging.getLogger(__name__)


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

    try:
        from apps.core.models import SystemConfiguration

        config = SystemConfiguration.objects.filter(pk=1).first()
        if config and config.deployment_mode:
            return config.deployment_mode
    except Exception:
        pass

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
    try:
        from apps.core.models import SystemConfiguration

        config = SystemConfiguration.objects.filter(pk=1).first()
        if config is not None:
            if config.is_initialized:
                return True
            # Explicitly uninitialized
            from apps.tenancy.models import Organization

            if not Organization.objects.exists():
                return False

        # If no SystemConfiguration record exists yet, check if database already has organizations
        from apps.tenancy.models import Organization

        first_org = Organization.objects.filter(is_active=True).first()
        if first_org is not None:
            # Auto-seed singleton record for backward compatibility
            mode = getattr(settings, "DEPLOYMENT_MODE", "dedicated") or "dedicated"
            SystemConfiguration.objects.get_or_create(
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
        # DB not ready or tables not yet migrated
        return True


def get_primary_organization() -> Organization | None:
    """Return the primary organization for dedicated single-business mode."""
    if not is_dedicated_mode():
        return None

    try:
        from apps.core.models import SystemConfiguration

        config = SystemConfiguration.objects.filter(pk=1).first()
        if config and config.primary_organization_id:
            return config.primary_organization

        from apps.tenancy.models import Organization

        return Organization.objects.filter(is_active=True).first()
    except Exception:
        return None

