"""REST API URL routes for HR resources."""

from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.hr.api import views

app_name = "hr_api"

router = DefaultRouter()
router.register("positions", views.PositionViewSet, basename="position")
router.register("employees", views.EmployeeViewSet, basename="employee")
router.register("shifts", views.ShiftViewSet, basename="shift")
router.register("attendance", views.AttendanceRecordViewSet, basename="attendance")
router.register("leave-types", views.LeaveTypeViewSet, basename="leave_type")
router.register("leave-balances", views.LeaveBalanceViewSet, basename="leave_balance")
router.register("leave-requests", views.LeaveRequestViewSet, basename="leave_request")

urlpatterns = [
    path("me/", views.SelfServiceProfileAPIView.as_view(), name="self_service_profile"),
    path("calendar/", views.HrCalendarApiView.as_view(), name="calendar"),
    *router.urls,
]
