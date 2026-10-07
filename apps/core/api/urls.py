"""Core API routing."""

from rest_framework.routers import DefaultRouter

from apps.core.api.views import AuditLogViewSet, NumberSequenceViewSet

router = DefaultRouter()
router.register("sequences", NumberSequenceViewSet, basename="sequence")
router.register("audit-logs", AuditLogViewSet, basename="audit-log")

urlpatterns = router.urls
