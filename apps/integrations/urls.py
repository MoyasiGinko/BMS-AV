"""URL routing for data imports and entity exports."""

from __future__ import annotations

from django.urls import path

from apps.integrations import views

app_name = "integrations"

urlpatterns = [
    # Imports
    path("imports/", views.imports_list_view, name="imports_list"),
    path("imports/upload/<str:entity_type>/", views.import_upload_view, name="import_upload"),
    path("imports/<uuid:job_id>/", views.import_preview_view, name="import_preview"),
    path("imports/<uuid:job_id>/commit/", views.import_commit_view, name="import_commit"),
    path("imports/<uuid:job_id>/status/", views.import_status_view, name="import_status"),
    path(
        "imports/template/<str:entity_type>/<str:file_format>/",
        views.template_download_view,
        name="template_download",
    ),
    # Exports
    path("exports/", views.exports_list_view, name="exports_list"),
    path("exports/trigger/<str:entity_type>/", views.export_trigger_view, name="export_trigger"),
    path("exports/<uuid:job_id>/status/", views.export_status_view, name="export_status"),
    path("exports/<uuid:job_id>/download/", views.export_download_view, name="export_download"),
]
