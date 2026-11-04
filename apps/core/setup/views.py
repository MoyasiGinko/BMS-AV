"""First-run setup wizard view."""

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

COMMON_COUNTRIES = [
    {"code": "BD", "name": "Bangladesh", "currency": "BDT", "symbol": "৳", "fiscal_month": 7, "timezone": "Asia/Dhaka"},
    {"code": "US", "name": "United States", "currency": "USD", "symbol": "$", "fiscal_month": 1, "timezone": "America/New_York"},
    {"code": "GB", "name": "United Kingdom", "currency": "GBP", "symbol": "£", "fiscal_month": 4, "timezone": "Europe/London"},
    {"code": "CA", "name": "Canada", "currency": "CAD", "symbol": "$", "fiscal_month": 1, "timezone": "America/Toronto"},
    {"code": "AU", "name": "Australia", "currency": "AUD", "symbol": "$", "fiscal_month": 7, "timezone": "Australia/Sydney"},
    {"code": "AE", "name": "United Arab Emirates", "currency": "AED", "symbol": "د.إ", "fiscal_month": 1, "timezone": "Asia/Dubai"},
    {"code": "SA", "name": "Saudi Arabia", "currency": "SAR", "symbol": "﷼", "fiscal_month": 1, "timezone": "Asia/Riyadh"},
    {"code": "IN", "name": "India", "currency": "INR", "symbol": "₹", "fiscal_month": 4, "timezone": "Asia/Kolkata"},
    {"code": "SG", "name": "Singapore", "currency": "SGD", "symbol": "$", "fiscal_month": 1, "timezone": "Asia/Singapore"},
    {"code": "MY", "name": "Malaysia", "currency": "MYR", "symbol": "RM", "fiscal_month": 1, "timezone": "Asia/Kuala_Lumpur"},
]

INDUSTRY_PRESETS = [
    {
        "id": "retail",
        "name": _("Retail & Point of Sale (POS)"),
        "description": _("Cash register, barcode scanning, catalog, inventory, and customer dues."),
        "modules": ["pos", "catalog", "inventory", "sales", "customers", "accounting"],
    },
    {
        "id": "wholesale",
        "name": _("Wholesale & Distribution"),
        "description": _("Sales orders, warehouse inventory, vendor bills, purchasing, and invoicing."),
        "modules": ["catalog", "inventory", "sales", "purchasing", "customers", "accounting"],
    },
    {
        "id": "services",
        "name": _("Services & Agency"),
        "description": _("Client management, proposals, invoicing, banking, expenses, and CRM."),
        "modules": ["sales", "customers", "accounting", "crm", "hr"],
    },
    {
        "id": "erp",
        "name": _("Comprehensive ERP Suite"),
        "description": _("Full operational suite with accounting, POS, HR, payroll, approvals, and AI."),
        "modules": [
            "pos", "catalog", "inventory", "sales", "purchasing", "customers",
            "accounting", "crm", "hr", "payroll", "approvals", "automation", "ai",
        ],
    },
]


@csrf_protect
def setup_wizard_view(request: HttpRequest) -> HttpResponse:
    """Multi-step setup wizard for initializing the system."""
    if is_system_initialized():
        messages.info(request, _("System is already initialized."))
        return redirect("/")

    if request.method == "POST":
        deployment_mode = request.POST.get("deployment_mode", "dedicated").strip().lower()
        system_name = request.POST.get("system_name", "Business OS").strip()
        entity_name = request.POST.get("entity_name", "").strip() or system_name
        admin_name = request.POST.get("admin_name", "System Administrator").strip()
        admin_email = request.POST.get("admin_email", "").strip()
        admin_password = request.POST.get("admin_password", "").strip()
        admin_password_confirm = request.POST.get("admin_password_confirm", "").strip()
        country = request.POST.get("country", "BD").strip().upper()
        currency = request.POST.get("currency", "BDT").strip().upper()
        timezone_str = request.POST.get("timezone", "Asia/Dhaka").strip()
        fiscal_year_start = int(request.POST.get("fiscal_year_start", 7))
        industry = request.POST.get("industry", "retail").strip().lower()
        selected_modules = request.POST.getlist("modules")

        errors: list[str] = []
        if not admin_email:
            errors.append(_("Email address is required."))
        if not admin_password:
            errors.append(_("Password is required."))
        elif len(admin_password) < 8:
            errors.append(_("Password must be at least 8 characters."))
        elif admin_password != admin_password_confirm:
            errors.append(_("Passwords do not match."))

        if errors:
            for err in errors:
                messages.error(request, err)
        else:
            try:
                admin_user, primary_org = provision_initial_system(
                    deployment_mode=deployment_mode,
                    system_name=system_name,
                    entity_name=entity_name,
                    admin_name=admin_name,
                    admin_email=admin_email,
                    admin_password=admin_password,
                    country=country,
                    currency=currency,
                    timezone_str=timezone_str,
                    fiscal_year_start=fiscal_year_start,
                    industry=industry,
                    enabled_modules=selected_modules or None,
                )

                # Log the administrator in
                login(request, admin_user, backend="django.contrib.auth.backends.ModelBackend")
                if primary_org:
                    request.session["active_org_id"] = primary_org.id

                messages.success(request, _("System initialized successfully."))
                if deployment_mode == "saas":
                    return redirect("backoffice:dashboard")
                return redirect("/")

            except ValidationError as err:
                messages.error(request, str(err))
            except Exception as err:
                logger.exception("Failed to initialize system.")
                messages.error(request, _("Failed to initialize system: %(error)s") % {"error": str(err)})

    available_modules = [
        {
            "key": m.key,
            "name": m.name,
            "description": m.description,
            "is_core": m.is_core,
            "icon": m.icon,
        }
        for m in registry.all()
    ]

    context: dict[str, Any] = {
        "countries": COMMON_COUNTRIES,
        "industry_presets": INDUSTRY_PRESETS,
        "available_modules": available_modules,
        "default_country": "BD",
        "default_currency": "BDT",
    }
    return render(request, "setup/wizard.html", context)


def setup_status_view(request: HttpRequest) -> JsonResponse:
    """Lightweight health and setup readiness check."""
    return JsonResponse(
        {
            "initialized": is_system_initialized(),
        }
    )

