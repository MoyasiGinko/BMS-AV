"""URL routing for Payroll web interface."""

from django.urls import path

from apps.payroll import views

app_name = "payroll"

urlpatterns = [
    # Runs
    path("runs/", views.payroll_run_list_view, name="run_list"),
    path("runs/create/", views.payroll_run_create_view, name="run_create"),
    path("runs/<uuid:public_id>/", views.payroll_run_detail_view, name="run_detail"),
    path("runs/<uuid:public_id>/review/", views.payroll_run_review_view, name="run_review"),
    path("runs/<uuid:public_id>/approve/", views.payroll_run_approve_view, name="run_approve"),
    path("runs/<uuid:public_id>/pay/", views.payroll_run_pay_view, name="run_pay"),
    path("runs/<uuid:public_id>/cancel/", views.payroll_run_cancel_view, name="run_cancel"),
    # Payslips & Self-service
    path("payslips/<uuid:public_id>/", views.payslip_detail_view, name="payslip_detail"),
    path("payslips/<uuid:public_id>/pdf/", views.payslip_pdf_download_view, name="payslip_pdf"),
    path("my-payslips/", views.my_payslips_view, name="my_payslips"),
    # Structures
    path("structures/", views.salary_structure_list_view, name="structure_list"),
    path("structures/create/", views.salary_structure_create_view, name="structure_create"),
    path("structures/<uuid:public_id>/edit/", views.salary_structure_edit_view, name="structure_edit"),
    # Components
    path("components/", views.salary_component_list_view, name="component_list"),
    path("components/create/", views.salary_component_create_view, name="component_create"),
    path("components/<uuid:public_id>/edit/", views.salary_component_edit_view, name="component_edit"),
    # Assignments
    path("assignments/", views.salary_assignment_list_view, name="assignment_list"),
    path("assignments/create/", views.salary_assignment_create_view, name="assignment_create"),
]
