"""Views for first-run setup wizard.

Enables the Software Owner (Superuser) to initialize the platform,
set up the initial organization and headquarters branch, and configure
the Organization Superadmin with highest authority to run the business.
"""

from __future__ import annotations

import logging
from typing import Any

from django.contrib import messages
from django.contrib.auth import login
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_protect

from apps.billing.registry import registry
from apps.core.exceptions import ValidationError
from apps.core.setup.services import provision_initial_system
from apps.core.system_mode import is_system_initialized

logger = logging.getLogger(__name__)

# Standard country presets for quick localization
COUNTRY_PRESETS = [
    {"code": "BD", "name": "Bangladesh", "currency": "BDT", "timezone": "Asia/Dhaka", "fiscal_month": 7},
    {"code": "US", "name": "United States", "currency": "USD", "timezone": "America/New_York", "fiscal_month": 1},
    {"code": "GB", "name": "United Kingdom", "currency": "GBP", "timezone": "Europe/London", "fiscal_month": 4},
    {"code": "IN", "name": "India", "currency": "INR", "timezone": "Asia/Kolkata", "fiscal_month": 4},
    {"code": "AE", "name": "United Arab Emirates", "currency": "AED", "timezone": "Asia/Dubai", "fiscal_month": 1},
    {"code": "SA", "name": "Saudi Arabia", "currency": "SAR", "timezone": "Asia/Riyadh", "fiscal_month": 1},
]

# Industry preset module templates
INDUSTRY_PRESETS = [
    {
        "id": "retail",
        "name": _("Retail & Point of Sale"),
        "description": _("Optimized for retail shops, checkout counter, barcode scanning, and inventory."),
        "modules": ["pos", "catalog", "inventory", "sales", "customers", "accounting"],
    },
    {
        "id": "supermarket",
        "name": _("Supermarket & Grocery"),
        "description": _("High-volume barcode scanning, batch expiry tracking, promotions, and suppliers."),
        "modules": ["pos", "catalog", "inventory", "purchasing", "sales", "customers", "accounting"],
    },
    {
        "id": "pharmacy",
        "name": _("Pharmacy & Healthcare"),
        "description": _("Batch/lot tracking, expiry management, prescription sales, and customer dues."),
        "modules": ["pos", "catalog", "inventory", "purchasing", "sales", "customers", "accounting"],
    },
    {
        "id": "wholesale",
        "name": _("Wholesale & Distribution"),
        "description": _("Bulk orders, multiple warehouses, price tiers, customer credit, and purchasing."),
        "modules": ["catalog", "inventory", "purchasing", "sales", "customers", "accounting"],
    },
    {
        "id": "custom",
        "name": _("Custom / Enterprise"),
        "description": _("Select exact modules suited for your enterprise requirements."),
        "modules": [
            "pos", "catalog", "inventory", "sales", "purchasing", "customers",
            "accounting", "crm", "hr", "payroll", "approvals", "automation", "ai",
        ],
    },
]


def _validate_setup_form(
    *,
    admin_email: str,
    admin_password: str,
    admin_password_confirm: str,
    superadmin_same: bool,
    superadmin_email: str,
    superadmin_password: str,
    superadmin_password_confirm: str,
) -> list[str]:
    errors: list[str] = []
    if not admin_email:
        errors.append(_("Software owner email address is required."))
    if not admin_password:
        errors.append(_("Software owner password is required."))
    elif len(admin_password) < 8:
        errors.append(_("Software owner password must be at least 8 characters."))
    elif admin_password != admin_password_confirm:
        errors.append(_("Software owner passwords do not match."))

    if not superadmin_same:
        if not superadmin_email:
            errors.append(_("Business Superadmin email address is required."))
        if not superadmin_password:
            errors.append(_("Business Superadmin password is required."))
        elif len(superadmin_password) < 8:
            errors.append(_("Business Superadmin password must be at least 8 characters."))
        elif superadmin_password != superadmin_password_confirm:
            errors.append(_("Business Superadmin passwords do not match."))

    return errors


@csrf_protect
def setup_wizard_view(request: HttpRequest) -> HttpResponse:
    """Multi-step setup wizard for initializing the system."""
    if is_system_initialized():
        messages.info(request, _("System is already initialized."))
        return redirect("/")

    if request.method == "POST":
        deployment_mode = "dedicated"
        system_name = request.POST.get("system_name", "Business OS").strip()
        entity_name = request.POST.get("entity_name", "").strip() or system_name
        branch_name = request.POST.get("branch_name", "Main Branch").strip() or "Main Branch"
        branch_code = request.POST.get("branch_code", "MAIN").strip() or "MAIN"

        admin_name = request.POST.get("admin_name", "System Administrator").strip()
        admin_email = request.POST.get("admin_email", "").strip()
        admin_password = request.POST.get("admin_password", "").strip()
        admin_password_confirm = request.POST.get("admin_password_confirm", "").strip()

        superadmin_same = request.POST.get("superadmin_same_as_owner") in ("true", "1", "on")
        superadmin_name = request.POST.get("superadmin_name", "").strip()
        superadmin_email = request.POST.get("superadmin_email", "").strip()
        superadmin_password = request.POST.get("superadmin_password", "").strip()
        superadmin_password_confirm = request.POST.get("superadmin_password_confirm", "").strip()

        country = request.POST.get("country", "BD").strip().upper()
        currency = request.POST.get("currency", "BDT").strip().upper()
        timezone_str = request.POST.get("timezone", "Asia/Dhaka").strip()
        fiscal_year_start = int(request.POST.get("fiscal_year_start", 7))
        industry = request.POST.get("industry", "retail").strip().lower()
        selected_modules = request.POST.getlist("modules")

        errors = _validate_setup_form(
            admin_email=admin_email,
            admin_password=admin_password,
            admin_password_confirm=admin_password_confirm,
            superadmin_same=superadmin_same,
            superadmin_email=superadmin_email,
            superadmin_password=superadmin_password,
            superadmin_password_confirm=superadmin_password_confirm,
        )

        if errors:
            for err in errors:
                messages.error(request, err)
        else:
            try:
                software_owner, primary_org, _sa = provision_initial_system(
                    deployment_mode=deployment_mode,
                    system_name=system_name,
                    entity_name=entity_name,
                    branch_name=branch_name,
                    branch_code=branch_code,
                    admin_name=admin_name,
                    admin_email=admin_email,
                    admin_password=admin_password,
                    superadmin_same_as_owner=superadmin_same,
                    superadmin_name=superadmin_name,
                    superadmin_email=superadmin_email,
                    superadmin_password=superadmin_password,
                    country=country,
                    currency=currency,
                    timezone_str=timezone_str,
                    fiscal_year_start=fiscal_year_start,
                    industry=industry,
                    enabled_modules=selected_modules or None,
                )

                # Log the software owner (superuser) in
                login(request, software_owner, backend="django.contrib.auth.backends.ModelBackend")
                if primary_org:
                    request.session["active_org_id"] = primary_org.id

                messages.success(request, _("System initialized successfully."))
                return redirect("/")

            except ValidationError as err:
                messages.error(request, str(err))
            except Exception as err:
                logger.exception("Failed to initialize system.")
                messages.error(request, _("Failed to initialize system: %(error)s") % {"error": str(err)})

    available_modules: list[dict[str, Any]] = [
        {
            "key": m.key,
            "name": m.name,
            "description": m.description,
            "is_core": m.is_core,
            "icon": m.icon,
        }
        for m in registry.all()
    ]

    return render(
        request,
        "setup/wizard.html",
        {
            "countries": COUNTRY_PRESETS,
            "industry_presets": INDUSTRY_PRESETS,
            "available_modules": available_modules,
        },
    )


def setup_status_view(request: HttpRequest) -> JsonResponse:
    """Lightweight health and setup readiness check."""
    return JsonResponse(
        {
            "initialized": is_system_initialized(),
        }
    )
