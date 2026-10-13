"""Core API routing."""

from rest_framework.routers import DefaultRouter

from apps.core.api.views import (
    ApiKeyViewSet,
    AuditLogViewSet,
    NotificationViewSet,
    NumberSequenceViewSet,
    UserNotificationPreferenceViewSet,
)

router = DefaultRouter()
router.register("sequences", NumberSequenceViewSet, basename="sequence")
router.register("audit-logs", AuditLogViewSet, basename="audit-log")
router.register("api-keys", ApiKeyViewSet, basename="api-key")
router.register(
    "notifications/preferences",
    UserNotificationPreferenceViewSet,
    basename="notification-preference",
)
router.register("notifications", NotificationViewSet, basename="notification")

urlpatterns = router.urls
