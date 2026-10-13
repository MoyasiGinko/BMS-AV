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
    # Webhooks v1
    path("webhooks/", views.webhook_endpoints_list_view, name="webhook_endpoints_list"),
    path("webhooks/new/", views.webhook_endpoint_create_view, name="webhook_endpoint_create"),
    path(
        "webhooks/<uuid:endpoint_id>/",
        views.webhook_endpoint_detail_view,
        name="webhook_endpoint_detail",
    ),
    path(
        "webhooks/<uuid:endpoint_id>/edit/",
        views.webhook_endpoint_edit_view,
        name="webhook_endpoint_edit",
    ),
    path(
        "webhooks/<uuid:endpoint_id>/delete/",
        views.webhook_endpoint_delete_view,
        name="webhook_endpoint_delete",
    ),
    path(
        "webhooks/<uuid:endpoint_id>/rotate-secret/",
        views.webhook_endpoint_rotate_secret_view,
        name="webhook_endpoint_rotate_secret",
    ),
    path(
        "webhooks/<uuid:endpoint_id>/ping/",
        views.webhook_endpoint_ping_view,
        name="webhook_endpoint_ping",
    ),
    path(
        "webhooks/deliveries/<uuid:delivery_id>/",
        views.webhook_delivery_detail_view,
        name="webhook_delivery_detail",
    ),
    path(
        "webhooks/deliveries/<uuid:delivery_id>/redeliver/",
        views.webhook_delivery_redeliver_view,
        name="webhook_delivery_redeliver",
    ),
    # Connector Framework
    path("connections/", views.connections_list_view, name="connections_list"),
    path("connections/new/", views.connection_create_view, name="connection_create"),
    path(
        "connections/new/<str:connector_type>/",
        views.connection_create_view,
        name="connection_create_typed",
    ),
    path(
        "connections/<uuid:connection_id>/",
        views.connection_detail_view,
        name="connection_detail",
    ),
    path(
        "connections/<uuid:connection_id>/edit/",
        views.connection_edit_view,
        name="connection_edit",
    ),
    path(
        "connections/<uuid:connection_id>/delete/",
        views.connection_delete_view,
        name="connection_delete",
    ),
    path(
        "connections/<uuid:connection_id>/test/",
        views.connection_test_view,
        name="connection_test",
    ),
    path(
        "connections/<uuid:connection_id>/sync/",
        views.connection_sync_view,
        name="connection_sync",
    ),
    path(
        "references/",
        views.external_references_list_view,
        name="external_references_list",
    ),
    # OAuth2 Application Registry & Authorized Tokens
    path("oauth/applications/", views.oauth_applications_list_view, name="oauth_applications_list"),
    path("oauth/applications/new/", views.oauth_application_create_view, name="oauth_application_create"),
    path(
        "oauth/applications/<uuid:app_id>/",
        views.oauth_application_detail_view,
        name="oauth_application_detail",
    ),
    path(
        "oauth/applications/<uuid:app_id>/edit/",
        views.oauth_application_edit_view,
        name="oauth_application_edit",
    ),
    path(
        "oauth/applications/<uuid:app_id>/delete/",
        views.oauth_application_delete_view,
        name="oauth_application_delete",
    ),
    path(
        "oauth/applications/<uuid:app_id>/rotate-secret/",
        views.oauth_application_rotate_secret_view,
        name="oauth_application_rotate_secret",
    ),
    path("oauth/authorized/", views.oauth_authorized_tokens_list_view, name="oauth_authorized_tokens"),
    path(
        "oauth/authorized/<int:token_id>/revoke/",
        views.oauth_revoke_token_view,
        name="oauth_revoke_token",
    ),
    # Inbound Webhooks
    path("inbound/", views.inbound_endpoints_list_view, name="inbound_endpoints_list"),
    path("inbound/new/", views.inbound_endpoint_create_view, name="inbound_endpoint_create"),
    path(
        "inbound/<uuid:endpoint_id>/",
        views.inbound_endpoint_detail_view,
        name="inbound_endpoint_detail",
    ),
    path(
        "inbound/<uuid:endpoint_id>/edit/",
        views.inbound_endpoint_edit_view,
        name="inbound_endpoint_edit",
    ),
    path(
        "inbound/<uuid:endpoint_id>/delete/",
        views.inbound_endpoint_delete_view,
        name="inbound_endpoint_delete",
    ),
    path(
        "inbound/<uuid:endpoint_id>/rotate-secret/",
        views.inbound_endpoint_rotate_secret_view,
        name="inbound_endpoint_rotate_secret",
    ),
    path("inbound/logs/", views.inbound_logs_list_view, name="inbound_logs_list"),
]
