"""URL routing for integrations and webhooks REST API."""

from __future__ import annotations

from rest_framework.routers import DefaultRouter

from apps.integrations.api.views import (
    WebhookDeliveryViewSet,
    WebhookEndpointViewSet,
)

router = DefaultRouter()
router.register("webhooks/deliveries", WebhookDeliveryViewSet, basename="webhook-delivery")
router.register("webhooks", WebhookEndpointViewSet, basename="webhook-endpoint")

urlpatterns = router.urls
