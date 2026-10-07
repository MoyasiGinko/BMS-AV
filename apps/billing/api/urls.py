"""Billing API URL routing."""

from __future__ import annotations

from rest_framework.routers import DefaultRouter

from apps.billing.api.views import (
    PlanViewSet,
    SubscriptionViewSet,
    UsageCounterViewSet,
)

app_name = "billing_api"

router = DefaultRouter()
router.register("plans", PlanViewSet, basename="plan")
router.register("subscription", SubscriptionViewSet, basename="subscription")
router.register("usage", UsageCounterViewSet, basename="usage")

urlpatterns = router.urls
