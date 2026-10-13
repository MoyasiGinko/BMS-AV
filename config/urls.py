"""Root URL configuration."""

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.core.views import (
    dashboard_view,
    dashboard_widget_partial_view,
    dismiss_onboarding_checklist_view,
    healthz_view,
    readyz_view,
    reset_onboarding_checklist_view,
    styleguide_view,
)

urlpatterns = [
    path("", dashboard_view, name="dashboard"),
    path("dashboard/", dashboard_view, name="dashboard_alias"),
    path(
        "dashboard/widget/<str:widget_id>/",
        dashboard_widget_partial_view,
        name="dashboard_widget_partial",
    ),
    path(
        "dashboard/checklist/dismiss/",
        dismiss_onboarding_checklist_view,
        name="dashboard_dismiss_checklist",
    ),
    path(
        "dashboard/checklist/reset/",
        reset_onboarding_checklist_view,
        name="dashboard_reset_checklist",
    ),
    path("_styleguide/", styleguide_view, name="styleguide"),
    path("healthz", healthz_view, name="healthz"),
    path("healthz/", healthz_view),
    path("readyz", readyz_view, name="readyz"),
    path("readyz/", readyz_view),
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("accounts/2fa/", include("allauth.mfa.urls")),
    path("oauth/", include("oauth2_provider.urls", namespace="oauth2_provider")),
    path("tenancy/", include("apps.tenancy.urls")),
    path("billing/", include("apps.billing.urls")),
    path("settings/", include("apps.tenancy.settings_urls")),
    path("backoffice/", include("apps.backoffice.urls", namespace="backoffice")),
    path("catalog/", include("apps.catalog.urls", namespace="catalog")),
    path("inventory/", include("apps.inventory.urls", namespace="inventory")),
    path("customers/", include("apps.customers.urls", namespace="customers")),
    path("sales/", include("apps.sales.urls", namespace="sales")),
    path("pos/", include("apps.pos.urls", namespace="pos")),
    path("reports/", include("apps.reports.urls", namespace="reports")),
    path("integrations/", include("apps.integrations.urls", namespace="integrations")),
    path("purchasing/", include("apps.purchasing.urls", namespace="purchasing")),
    path("accounting/", include("apps.accounting.urls", namespace="accounting")),
    path("crm/", include("apps.crm.urls", namespace="crm")),
    path("hr/", include("apps.hr.urls", namespace="hr")),
    path("payroll/", include("apps.payroll.urls", namespace="payroll")),
    path("approvals/", include("apps.approvals.urls", namespace="approvals")),
    path("automation/", include("apps.automation.urls", namespace="automation")),
    path("notifications/", include("apps.core.notification_urls", namespace="notifications")),
    path("api/v1/", include("config.api_urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="api-schema"), name="api-docs"),
]
