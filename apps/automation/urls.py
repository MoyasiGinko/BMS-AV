"""URL configuration for the automation engine web interface."""

from django.urls import path

from apps.automation import views

app_name = "automation"

urlpatterns = [
    path("", views.rule_list_view, name="rule_list"),
    path("templates/", views.template_list_view, name="template_list"),
    path("templates/<str:template_key>/use/", views.template_instantiate_view, name="template_use"),
    path("rules/new/", views.rule_create_view, name="rule_create"),
    path("rules/<str:rule_id>/edit/", views.rule_edit_view, name="rule_edit"),
    path("rules/<str:rule_id>/toggle/", views.rule_toggle_view, name="rule_toggle"),
    path("rules/<str:rule_id>/delete/", views.rule_delete_view, name="rule_delete"),
    path("rules/<str:rule_id>/test/", views.rule_test_view, name="rule_test"),
    path("runs/", views.run_list_view, name="run_list"),
    path("runs/<str:run_id>/", views.run_detail_view, name="run_detail"),
]
