"""Billing API URL routing."""

from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.billing.api.views import (
    GatewayWebhookView,
    PlanViewSet,
    SubscriptionInvoiceViewSet,
    SubscriptionViewSet,
    UsageCounterViewSet,
)

app_name = "billing_api"

router = DefaultRouter()
router.register("plans", PlanViewSet, basename="plan")
router.register("subscription", SubscriptionViewSet, basename="subscription")
router.register("usage", UsageCounterViewSet, basename="usage")
router.register("invoices", SubscriptionInvoiceViewSet, basename="invoice")

urlpatterns = [
    path("webhook/", GatewayWebhookView.as_view(), name="gateway_webhook"),
    *router.urls,
]
