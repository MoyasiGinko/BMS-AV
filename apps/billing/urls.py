"""Billing UI URL configuration."""

from __future__ import annotations

from django.urls import path

from apps.billing.views import (
    cancel_subscription_view,
    change_plan_view,
    invoice_detail_view,
    subscription_dashboard_view,
)

app_name = "billing"

urlpatterns = [
    path("", subscription_dashboard_view, name="dashboard"),
    path("change-plan/", change_plan_view, name="change_plan"),
    path("cancel/", cancel_subscription_view, name="cancel"),
    path("invoices/<uuid:invoice_id>/", invoice_detail_view, name="invoice_detail"),
]
