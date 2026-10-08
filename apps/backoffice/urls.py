"""URL routing for the Back-Office operations control plane."""

from django.urls import path

from apps.backoffice.views import (
    dashboard_view,
    impersonate_stop_view,
    impersonate_tenant_view,
    impersonate_user_view,
    outbox_detail_view,
    outbox_list_view,
    outbox_retry_view,
    subscription_override_view,
    tenant_detail_view,
    tenant_list_view,
    tenant_status_update_view,
    webhook_detail_view,
    webhook_list_view,
)

app_name = "backoffice"

urlpatterns = [
    path("", dashboard_view, name="dashboard"),
    path("tenants/", tenant_list_view, name="tenant_list"),
    path("tenants/<uuid:public_id>/", tenant_detail_view, name="tenant_detail"),
    path(
        "tenants/<uuid:public_id>/override-subscription/",
        subscription_override_view,
        name="subscription_override",
    ),
    path(
        "tenants/<uuid:public_id>/update-status/",
        tenant_status_update_view,
        name="tenant_status_update",
    ),
    path(
        "tenants/<uuid:public_id>/impersonate/",
        impersonate_tenant_view,
        name="impersonate_tenant",
    ),
    path("impersonate/user/<int:user_id>/", impersonate_user_view, name="impersonate_user"),
    path("impersonate/stop/", impersonate_stop_view, name="impersonate_stop"),
    path("jobs/", outbox_list_view, name="outbox_list"),
    path("jobs/<uuid:event_id>/", outbox_detail_view, name="outbox_detail"),
    path("jobs/<uuid:event_id>/retry/", outbox_retry_view, name="outbox_retry"),
    path("webhooks/", webhook_list_view, name="webhook_list"),
    path("webhooks/<str:event_id>/", webhook_detail_view, name="webhook_detail"),
]
