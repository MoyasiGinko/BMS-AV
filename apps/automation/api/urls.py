"""DRF router URLs for the automation engine."""

from rest_framework.routers import DefaultRouter

from apps.automation.api.views import (
    AutomationRuleViewSet,
    AutomationRunViewSet,
    AutomationTemplateViewSet,
)

router = DefaultRouter()
router.register("rules", AutomationRuleViewSet, basename="automation-rules")
router.register("runs", AutomationRunViewSet, basename="automation-runs")
router.register("templates", AutomationTemplateViewSet, basename="automation-templates")

urlpatterns = router.urls
