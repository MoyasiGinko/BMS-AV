"""URL patterns for Human Resources web interface."""

from __future__ import annotations

from django.urls import path

from apps.hr import views

app_name = "hr"

urlpatterns = [
    # Employees
    path("employees/", views.employee_list_view, name="employee_list"),
    path("employees/new/", views.employee_create_view, name="employee_create"),
    path("employees/<uuid:public_id>/", views.employee_detail_view, name="employee_detail"),
    path("employees/<uuid:public_id>/edit/", views.employee_edit_view, name="employee_edit"),
    path(
        "employees/<uuid:public_id>/status/",
        views.employee_status_transition_view,
        name="employee_status_transition",
    ),
    path(
        "employees/<uuid:public_id>/documents/upload/",
        views.employee_document_upload_view,
        name="employee_document_upload",
    ),
    path(
        "documents/<uuid:doc_public_id>/delete/",
        views.employee_document_delete_view,
        name="employee_document_delete",
    ),
    # Self-Service Profile
    path("me/", views.self_service_profile_view, name="self_service_profile"),
    # Positions
    path("positions/", views.position_list_view, name="position_list"),
    path("positions/new/", views.position_create_view, name="position_create"),
    path("positions/<uuid:public_id>/edit/", views.position_edit_view, name="position_edit"),
]
