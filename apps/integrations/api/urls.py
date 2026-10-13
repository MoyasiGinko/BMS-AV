"""URL routing for integrations and webhooks REST API."""

from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.integrations.api.views import (
    ExternalReferenceViewSet,
    IntegrationConnectionViewSet,
    IntegrationSyncLogViewSet,
    WebhookDeliveryViewSet,
    WebhookEndpointViewSet,
    ZapierHooksAPIView,
    ZapierSampleAPIView,
)

router = DefaultRouter()
router.register("connections", IntegrationConnectionViewSet, basename="integration-connection")
router.register("references", ExternalReferenceViewSet, basename="external-reference")
router.register("logs", IntegrationSyncLogViewSet, basename="integration-sync-log")
router.register("webhooks/deliveries", WebhookDeliveryViewSet, basename="webhook-delivery")
router.register("webhooks", WebhookEndpointViewSet, basename="webhook-endpoint")

urlpatterns = [
    *router.urls,
    path("zapier/hooks/", ZapierHooksAPIView.as_view(), name="zapier-hooks"),
    path("zapier/sample/<str:event_type>/", ZapierSampleAPIView.as_view(), name="zapier-sample"),
]
