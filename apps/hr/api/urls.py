"""REST API URL routes for HR resources."""

from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.hr.api import views

app_name = "hr_api"

router = DefaultRouter()
router.register("positions", views.PositionViewSet, basename="position")
router.register("employees", views.EmployeeViewSet, basename="employee")

urlpatterns = [
    path("me/", views.SelfServiceProfileAPIView.as_view(), name="self_service_profile"),
    *router.urls,
]
