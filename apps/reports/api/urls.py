"""DRF API routing for the Reports module."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.reports.api import views

app_name = "reports-api"

router = DefaultRouter()
router.register("saved", views.SavedReportViewSet, basename="saved-report")
router.register("schedules", views.ReportScheduleViewSet, basename="report-schedule")

urlpatterns = [
    path("", include(router.urls)),
    path("builder/", views.CustomReportBuilderAPIView.as_view(), name="report-builder"),
    path("summaries/", views.DailySummaryAPIView.as_view(), name="daily-summaries"),
    # Business Analytics (P6-04)
    path("analytics/cohort/", views.CustomerCohortAnalyticsAPIView.as_view(), name="analytics-cohort"),
    path("analytics/abc/", views.ProductAbcAnalyticsAPIView.as_view(), name="analytics-abc"),
    path("analytics/margins/", views.MarginAnalyticsAPIView.as_view(), name="analytics-margins"),
    path(
        "analytics/forecasting/",
        views.DemandForecastAnalyticsAPIView.as_view(),
        name="analytics-forecasting",
    ),
]
