"""REST API URL routing for Approvals."""

from rest_framework.routers import DefaultRouter

from apps.approvals.api.views import (
    ApprovalRequestViewSet,
    ApprovalRuleViewSet,
)

router = DefaultRouter()
router.register("rules", ApprovalRuleViewSet, basename="approval-rule")
router.register("requests", ApprovalRequestViewSet, basename="approval-request")

urlpatterns = router.urls
