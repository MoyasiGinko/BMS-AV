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
    # Shifts
    path("shifts/", views.shift_list_view, name="shift_list"),
    path("shifts/new/", views.shift_create_view, name="shift_create"),
    path("shifts/<uuid:public_id>/edit/", views.shift_edit_view, name="shift_edit"),
    # Attendance
    path("attendance/", views.attendance_list_view, name="attendance_list"),
    path("attendance/check-in/", views.attendance_check_in_view, name="attendance_check_in"),
    path("attendance/check-out/", views.attendance_check_out_view, name="attendance_check_out"),
    path("attendance/manual/", views.attendance_manual_record_view, name="attendance_manual_record"),
    # Leave Types
    path("leave-types/", views.leave_type_list_view, name="leave_type_list"),
    path("leave-types/new/", views.leave_type_create_view, name="leave_type_create"),
    path("leave-types/<uuid:public_id>/edit/", views.leave_type_edit_view, name="leave_type_edit"),
    # Leave Balances
    path("leave-balances/", views.leave_balance_list_view, name="leave_balance_list"),
    path("leave-balances/allocate/", views.leave_balance_allocate_view, name="leave_balance_allocate"),
    # Leave Requests
    path("leave-requests/", views.leave_request_list_view, name="leave_request_list"),
    path("leave-requests/new/", views.leave_request_create_view, name="leave_request_create"),
    path(
        "leave-requests/<uuid:public_id>/approve/",
        views.leave_request_approve_view,
        name="leave_request_approve",
    ),
    path(
        "leave-requests/<uuid:public_id>/reject/",
        views.leave_request_reject_view,
        name="leave_request_reject",
    ),
    path(
        "leave-requests/<uuid:public_id>/cancel/",
        views.leave_request_cancel_view,
        name="leave_request_cancel",
    ),
    # Calendar
    path("calendar/", views.hr_calendar_view, name="calendar"),
]
