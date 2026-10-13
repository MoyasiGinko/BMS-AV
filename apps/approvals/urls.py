"""URL patterns for the Approvals engine web UI."""

from django.urls import path

from apps.approvals import views

app_name = "approvals"

urlpatterns = [
    path("", views.inbox, name="inbox"),
    path("requests/<int:pk>/", views.request_detail, name="request_detail"),
    path("requests/<int:pk>/approve/", views.request_approve, name="request_approve"),
    path("requests/<int:pk>/reject/", views.request_reject, name="request_reject"),
    path("requests/<int:pk>/cancel/", views.request_cancel, name="request_cancel"),
    path("rules/", views.rule_list, name="rule_list"),
    path("rules/new/", views.rule_create, name="rule_create"),
    path("rules/<int:pk>/edit/", views.rule_edit, name="rule_edit"),
    path("rules/<int:pk>/delete/", views.rule_delete, name="rule_delete"),
    path("history/", views.history_list, name="history_list"),
]
