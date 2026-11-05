"""First-run system setup and provisioning service.

Bootstraps the software with:
- Software Owner (Superuser): Highest global authority. Sets up software, organization, branches, and sets the Superadmin.
- Organization & Headquarters Branch: Company workspace and operating location.
- Organization Superadmin: Highest authority from user perspective for running their business.
- Active functional modules and industry presets.
"""

from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.billing.services import seed_default_plans
from apps.core.exceptions import ValidationError
from apps.core.models import SystemConfiguration
from apps.tenancy.models import Membership, Organization, Role
from apps.tenancy.services import provision_organization

logger = logging.getLogger(__name__)


def _create_or_update_admin(
    *,
    admin_name: str,
    clean_email: str,
    admin_password: str,
) -> Any:
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
        return user_model.objects.create_superuser(
            email=clean_email,
            password=admin_password,
            **extra_user_fields,
        )

    admin_user.set_password(admin_password)
    admin_user.is_superuser = True
    admin_user.is_staff = True
    for k, v in extra_user_fields.items():
        setattr(admin_user, k, v)
    admin_user.save()
    return admin_user


def _create_or_update_business_user(
    *,
    user_name: str,
    clean_email: str,
    user_password: str,
) -> Any:
    user_model = get_user_model()
    extra_user_fields: dict[str, Any] = {}
    if hasattr(user_model, "name"):
        extra_user_fields["name"] = user_name.strip()
    elif hasattr(user_model, "first_name"):
        name_parts = user_name.strip().split(" ", 1)
        extra_user_fields["first_name"] = name_parts[0] if name_parts else "Superadmin"
        if len(name_parts) > 1:
            extra_user_fields["last_name"] = name_parts[1]

    user = user_model.objects.filter(email__iexact=clean_email).first()
    if not user:
        return user_model.objects.create_user(
            email=clean_email,
            password=user_password,
            is_staff=False,
            is_superuser=False,
            **extra_user_fields,
        )

    user.set_password(user_password)
    for k, v in extra_user_fields.items():
        setattr(user, k, v)
    user.save()
    return user


def _provision_dedicated_org(
    *,
    software_owner: Any,
    business_superadmin: Any,
    entity_name: str,
    system_name: str,
    branch_name: str = "Main Branch",
    branch_code: str = "MAIN",
    currency: str = "BDT",
    country: str = "BD",
    timezone_str: str = "Asia/Dhaka",
    fiscal_year_start: int = 7,
    industry: str = "retail",
    enabled_modules: list[str] | None = None,
) -> Organization:
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
        owner=business_superadmin,
        base_currency=currency.upper(),
        country=country.upper() if country else "",
        timezone_str=timezone_str,
        fiscal_year_start=fiscal_year_start,
        branch_name=branch_name.strip() or "Main Branch",
        branch_code=branch_code.strip() or "MAIN",
        actor=software_owner,
    )

    # If software owner is separate from business superadmin, also record active membership
    if software_owner.pk != business_superadmin.pk:
        superadmin_role = Role.all_tenants.filter(organization=primary_org, name="Superadmin").first()
        Membership.all_tenants.get_or_create(
            organization=primary_org,
            user=software_owner,
            defaults={
                "role": superadmin_role,
                "is_owner": False,
                "status": Membership.STATUS_ACTIVE,
            },
        )

    if enabled_modules:
        org_settings = primary_org.settings if isinstance(primary_org.settings, dict) else {}
        org_settings["enabled_modules"] = enabled_modules
        org_settings["industry_preset"] = industry
        primary_org.settings = org_settings
        primary_org.save(update_fields=["settings"])

    return primary_org


@transaction.atomic
def provision_initial_system(
    *,
    deployment_mode: str = "dedicated",
    system_name: str,
    entity_name: str,
    admin_name: str,
    admin_email: str,
    admin_password: str,
    branch_name: str = "Main Branch",
    branch_code: str = "MAIN",
    superadmin_same_as_owner: bool = True,
    superadmin_name: str = "",
    superadmin_email: str = "",
    superadmin_password: str = "",
    country: str = "BD",
    currency: str = "BDT",
    timezone_str: str = "Asia/Dhaka",
    fiscal_year_start: int = 7,
    industry: str = "retail",
    enabled_modules: list[str] | None = None,
) -> tuple[Any, Organization | None, Any]:
    """Execute complete atomic first-run setup.

    Returns (software_owner, primary_org, business_superadmin).
    """
    clean_mode = str(deployment_mode).strip().lower()
    if clean_mode not in (SystemConfiguration.MODE_DEDICATED, SystemConfiguration.MODE_SAAS):
        raise ValidationError(f"Invalid deployment mode: {deployment_mode}")

    clean_email = admin_email.strip().lower()
    if not clean_email or "@" not in clean_email:
        raise ValidationError("Valid software owner email is required.")

    if not admin_password or len(admin_password) < 8:
        raise ValidationError("Software owner password must be at least 8 characters.")

    # 1. Create or retrieve Software Owner (Superuser)
    software_owner = _create_or_update_admin(
        admin_name=admin_name,
        clean_email=clean_email,
        admin_password=admin_password,
    )

    # 2. Resolve Business Superadmin (Organization Highest Authority)
    clean_sa_email = superadmin_email.strip().lower()
    if superadmin_same_as_owner or not clean_sa_email:
        business_superadmin = software_owner
    else:
        if "@" not in clean_sa_email:
            raise ValidationError("Valid business superadmin email is required.")
        if not superadmin_password or len(superadmin_password) < 8:
            raise ValidationError("Business superadmin password must be at least 8 characters.")
        business_superadmin = _create_or_update_business_user(
            user_name=superadmin_name.strip() or "Business Superadmin",
            clean_email=clean_sa_email,
            user_password=superadmin_password,
        )

    primary_org: Organization | None = None

    # 3. Dedicated Business Organization Setup
    if clean_mode == SystemConfiguration.MODE_DEDICATED:
        primary_org = _provision_dedicated_org(
            software_owner=software_owner,
            business_superadmin=business_superadmin,
            entity_name=entity_name,
            system_name=system_name,
            branch_name=branch_name,
            branch_code=branch_code,
            currency=currency,
            country=country,
            timezone_str=timezone_str,
            fiscal_year_start=fiscal_year_start,
            industry=industry,
            enabled_modules=enabled_modules,
        )

    # 4. SaaS Platform Setup (Legacy/optional)
    elif clean_mode == SystemConfiguration.MODE_SAAS:
        try:
            seed_default_plans()
        except Exception:
            logger.exception("Failed to seed default SaaS billing plans during setup.")

    # 5. Finalize SystemConfiguration Singleton
    config = SystemConfiguration.get_solo()
    config.deployment_mode = clean_mode
    config.system_name = system_name.strip() or (primary_org.name if primary_org else "Business OS")
    config.is_initialized = True
    config.primary_organization = primary_org
    config.allow_public_signup = clean_mode == SystemConfiguration.MODE_SAAS
    config.setup_completed_at = timezone.now()
    config.setup_completed_by = software_owner
    config.save()

    logger.info(
        "System successfully initialized in %s mode. Owner: %s, Org Superadmin: %s",
        clean_mode,
        clean_email,
        business_superadmin.email,
    )
    return software_owner, primary_org, business_superadmin
