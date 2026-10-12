"""URL configuration for the CRM REST API."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.crm.api import views

router = DefaultRouter()
router.register("leads", views.LeadViewSet, basename="lead")
router.register("pipelines", views.PipelineViewSet, basename="pipeline")
router.register("opportunities", views.OpportunityViewSet, basename="opportunity")
router.register("interactions", views.InteractionViewSet, basename="interaction")
router.register("tasks", views.CrmTaskViewSet, basename="task")

urlpatterns = [
    path("", include(router.urls)),
    path(
        "customer-360/<uuid:customer_public_id>/",
        views.Customer360APIView.as_view(),
        name="customer-360",
    ),
]
