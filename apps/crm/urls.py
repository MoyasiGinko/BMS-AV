"""URL routes for the CRM module."""

from django.urls import path

from apps.crm import views

app_name = "crm"

urlpatterns = [
    # Leads
    path("leads/", views.lead_list_view, name="lead_list"),
    path("leads/create/", views.lead_create_view, name="lead_create"),
    path("leads/<uuid:public_id>/", views.lead_detail_view, name="lead_detail"),
    path("leads/<uuid:public_id>/edit/", views.lead_edit_view, name="lead_edit"),
    path("leads/<uuid:public_id>/convert/", views.lead_convert_view, name="lead_convert"),
    # Pipelines & Deals (Kanban)
    path("pipeline/", views.pipeline_kanban_view, name="pipeline_kanban"),
    path("opportunities/create/", views.opportunity_create_view, name="opportunity_create"),
    path("opportunities/<uuid:public_id>/", views.opportunity_detail_view, name="opportunity_detail"),
    path(
        "opportunities/<uuid:public_id>/stage/<int:stage_id>/",
        views.opportunity_stage_move_view,
        name="opportunity_stage_move",
    ),
    # Customer 360 & Inactive Segments
    path("customers/360/", views.customer_360_index_view, name="customer_360_index"),
    path("customers/<int:customer_id>/360/", views.customer_360_view, name="customer_360"),
    path("segments/inactive/", views.inactive_customers_view, name="inactive_customers"),
    # Interactions & Tasks
    path("interactions/log/", views.log_interaction_view, name="log_interaction"),
    path("tasks/", views.task_list_view, name="task_list"),
    path("tasks/<uuid:public_id>/complete/", views.task_toggle_complete_view, name="task_toggle_complete"),
]
