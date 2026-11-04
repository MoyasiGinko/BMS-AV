"""First-run system setup and provisioning service.

Atomically bootstraps the system in either:
- "dedicated" mode (Single company/organization, direct module access, no billing gates)
- "saas" mode (Multi-tenant platform, subscription plans, platform backoffice)
"""

from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.core.exceptions import ValidationError
from apps.core.models import SystemConfiguration
from apps.tenancy.models import Organization

logger = logging.getLogger(__name__)


@transaction.atomic
def provision_initial_system(
    *,
    deployment_mode: str,
    system_name: str,
    entity_name: str,
    admin_name: str,
    admin_email: str,
    admin_password: str,
    country: str = "BD",
    currency: str = "BDT",
    timezone_str: str = "Asia/Dhaka",
    fiscal_year_start: int = 7,
    industry: str = "retail",
    enabled_modules: list[str] | None = None,
) -> tuple[Any, Organization | None]:
    """Execute complete atomic first-run setup.

    Returns (admin_user, primary_org_or_none).
    """
    clean_mode = str(deployment_mode).strip().lower()
    if clean_mode not in (SystemConfiguration.MODE_DEDICATED, SystemConfiguration.MODE_SAAS):
        raise ValidationError(f"Invalid deployment mode: {deployment_mode}")

    clean_email = admin_email.strip().lower()
    if not clean_email or "@" not in clean_email:
        raise ValidationError("Valid administrator email is required.")

    if not admin_password or len(admin_password) < 8:
        raise ValidationError("Administrator password must be at least 8 characters.")

    # 1. Create or retrieve Superadmin User
    user_model = get_user_model()
    extra_user_fields: dict[str, Any] = {}
    if hasattr(user_model, "name"):
        extra_user_fields["name"] = admin_name.strip()
    elif hasattr(user_model, "first_name"):
        name_parts = admin_name.strip().split(" ", 1)
        extra_user_fields["first_name"] = name_parts[0] if name_parts else "Admin"
        if len(name_parts) > 1:
            extra_user_fields["last_name"] = name_parts[1]

    admin_user = user_model.objects.filter(email__iexact=clean_email).first()
    if not admin_user:
        admin_user = user_model.objects.create_superuser(
            email=clean_email,
            password=admin_password,
            **extra_user_fields,
        )
    else:
        admin_user.set_password(admin_password)
        admin_user.is_superuser = True
        admin_user.is_staff = True
        for k, v in extra_user_fields.items():
            setattr(admin_user, k, v)
        admin_user.save()

    primary_org: Organization | None = None

    # 2. Dedicated Single Business Setup
    if clean_mode == SystemConfiguration.MODE_DEDICATED:
        from apps.tenancy.services import provision_organization

        org_name = entity_name.strip() or system_name.strip() or "My Business"
        base_slug = slugify(org_name) or "business"
        slug = base_slug
        counter = 1
        while Organization.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1

        primary_org = provision_organization(
            name=org_name,
            slug=slug,
            owner=admin_user,
            base_currency=currency.upper(),
            country=country.upper() if country else "",
            timezone_str=timezone_str,
            fiscal_year_start=fiscal_year_start,
            branch_name="Main Branch",
            warehouse_name="Main Warehouse",
            actor=admin_user,
        )

        # Store chosen enabled modules in organization settings
        if enabled_modules:
            org_settings = primary_org.settings if isinstance(primary_org.settings, dict) else {}
            org_settings["enabled_modules"] = enabled_modules
            org_settings["industry_preset"] = industry
            primary_org.settings = org_settings
            primary_org.save(update_fields=["settings"])

    # 3. SaaS Platform Setup
    elif clean_mode == SystemConfiguration.MODE_SAAS:
        # Seed default billing plans and functional modules
        try:
            from apps.billing.services import seed_default_plans

            seed_default_plans()
        except Exception:
            logger.exception("Failed to seed default SaaS billing plans during setup.")

    # 4. Finalize SystemConfiguration Singleton
    config = SystemConfiguration.get_solo()
    config.deployment_mode = clean_mode
    config.system_name = system_name.strip() or (primary_org.name if primary_org else "Business OS")
    config.is_initialized = True
    config.primary_organization = primary_org
    config.allow_public_signup = clean_mode == SystemConfiguration.MODE_SAAS
    config.setup_completed_at = timezone.now()
    config.setup_completed_by = admin_user
    config.save()

    logger.info("System successfully initialized in %s mode by %s", clean_mode, clean_email)
    return admin_user, primary_org
