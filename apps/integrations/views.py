"""Views for data imports (validate-preview-commit), entity exports, and templates."""

from __future__ import annotations

import logging
from typing import Any

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _

from apps.core.event_catalog import list_events_by_module
from apps.core.permissions import permission_required
from apps.integrations import selectors, services
from apps.integrations.connectors import connector_registry
from apps.integrations.forms import (
    DataRetentionPolicyForm,
    DataSubjectRequestForm,
    InboundWebhookEndpointForm,
    IntegrationConnectionForm,
    OAuthApplicationForm,
    TenantExportJobForm,
    TenantImportJobForm,
    WebhookEndpointForm,
)
from apps.integrations.importers import get_importer
from apps.integrations.models import (
    ConnectorType,
    EntityType,
    FileFormat,
    ImportJobStatus,
)
from apps.tenancy.models import Organization

logger = logging.getLogger(__name__)


def _get_active_org(request: HttpRequest) -> Organization:
    org = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied(_("No active organization found."))
    return org


@permission_required("integrations.view")
def imports_list_view(request: HttpRequest) -> HttpResponse:
    """List all import jobs for the active tenant."""
    org = _get_active_org(request)
    entity_filter = request.GET.get("entity_type")
    jobs = selectors.list_import_jobs(org, entity_type=entity_filter)

    return render(
        request,
        "integrations/imports_list.html",
        {
            "jobs": jobs,
            "selected_entity": entity_filter,
            "entity_choices": EntityType.choices,
        },
    )


@permission_required("integrations.import")
def import_upload_view(request: HttpRequest, entity_type: str) -> HttpResponse:
    """Upload a CSV or XLSX file and immediately validate it for preview."""
    org = _get_active_org(request)
    if entity_type not in EntityType.values:
        raise Http404(_("Unknown entity type."))

    importer = get_importer(entity_type)

    if request.method == "POST":
        upload_file = request.FILES.get("file")
        if not upload_file:
            messages.error(request, _("Please select a file to upload."))
            return redirect("integrations:import_upload", entity_type=entity_type)

        fname = (upload_file.name or "").lower()
        if fname.endswith(".xlsx"):
            file_format = FileFormat.XLSX
        elif fname.endswith(".csv"):
            file_format = FileFormat.CSV
        else:
            messages.error(request, _("Unsupported file format. Please upload a .csv or .xlsx file."))
            return redirect("integrations:import_upload", entity_type=entity_type)

        update_existing = request.POST.get("update_existing") == "1"
        create_missing = request.POST.get("create_missing") == "1"

        try:
            job = services.create_import_job(
                organization=org,
                entity_type=entity_type,
                file=upload_file,
                file_format=file_format,
                options={
                    "update_existing": update_existing,
                    "create_missing": create_missing,
                },
                actor=request.user,
                auto_validate=True,
            )
            return redirect("integrations:import_preview", job_id=job.public_id)
        except Exception as exc:
            messages.error(request, _("Validation failed: %(error)s") % {"error": str(exc)})
            return redirect("integrations:import_upload", entity_type=entity_type)

    return render(
        request,
        "integrations/import_upload.html",
        {
            "entity_type": entity_type,
            "importer": importer,
        },
    )


@permission_required("integrations.view")
def import_preview_view(request: HttpRequest, job_id: str) -> HttpResponse:
    """Inspect validation results, review error rows, and commit or discard import."""
    org = _get_active_org(request)
    job = selectors.get_import_job(org, job_id=job_id)
    if not job:
        raise Http404(_("Import job not found."))

    return render(
        request,
        "integrations/import_preview.html",
        {
            "job": job,
            "can_commit": job.status == ImportJobStatus.VALIDATED and job.valid_rows > 0,
        },
    )


@permission_required("integrations.import")
def import_commit_view(request: HttpRequest, job_id: str) -> HttpResponse:
    """Execute transactional commit of validated import rows."""
    org = _get_active_org(request)
    job = selectors.get_import_job(org, job_id=job_id)
    if not job:
        raise Http404(_("Import job not found."))

    if request.method != "POST":
        return redirect("integrations:import_preview", job_id=job_id)

    try:
        job = services.commit_import_job(job.public_id, actor=request.user)
        messages.success(
            request,
            _("Import completed successfully: %(created)d created, %(updated)d updated, %(skipped)d skipped.")
            % {
                "created": job.created_count,
                "updated": job.updated_count,
                "skipped": job.skipped_count,
            },
        )
    except Exception as exc:
        messages.error(request, _("Commit failed: %(error)s") % {"error": str(exc)})

    if getattr(request, "htmx", False):
        return render(request, "integrations/partials/import_status.html", {"job": job})

    return redirect("integrations:import_preview", job_id=job_id)


@permission_required("integrations.view")
def import_status_view(request: HttpRequest, job_id: str) -> HttpResponse:
    """HTMX polling endpoint for import job status."""
    org = _get_active_org(request)
    job = selectors.get_import_job(org, job_id=job_id)
    if not job:
        raise Http404(_("Import job not found."))

    return render(request, "integrations/partials/import_status.html", {"job": job})


@permission_required("integrations.view")
def template_download_view(request: HttpRequest, entity_type: str, file_format: str) -> HttpResponse:
    """Download official blank CSV or XLSX import template with sample rows."""
    if entity_type not in EntityType.values:
        raise Http404(_("Unknown entity type."))

    importer = get_importer(entity_type)
    filename, content = importer.generate_template(file_format)

    content_type = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if file_format.lower() == "xlsx"
        else "text/csv; charset=utf-8"
    )

    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@permission_required("integrations.view")
def exports_list_view(request: HttpRequest) -> HttpResponse:
    """List entity export jobs."""
    org = _get_active_org(request)
    entity_filter = request.GET.get("entity_type")
    jobs = selectors.list_export_jobs(org, entity_type=entity_filter)

    return render(
        request,
        "integrations/exports_list.html",
        {
            "jobs": jobs,
            "selected_entity": entity_filter,
            "entity_choices": EntityType.choices,
        },
    )


@permission_required("integrations.export")
def export_trigger_view(request: HttpRequest, entity_type: str) -> HttpResponse:
    """Trigger background entity export job."""
    org = _get_active_org(request)
    if entity_type not in EntityType.values:
        raise Http404(_("Unknown entity type."))

    file_format = request.POST.get("file_format", FileFormat.CSV)
    if file_format not in FileFormat.values:
        file_format = FileFormat.CSV

    job = services.create_export_job(
        organization=org,
        entity_type=entity_type,
        file_format=file_format,
        actor=request.user,
        run_async=True,
    )

    if getattr(request, "htmx", False):
        return render(request, "integrations/partials/export_status.html", {"job": job})

    messages.info(request, _("Export job enqueued. Download will be available shortly."))
    return redirect("integrations:exports_list")


@permission_required("integrations.view")
def export_status_view(request: HttpRequest, job_id: str) -> HttpResponse:
    """HTMX polling endpoint for export job status."""
    org = _get_active_org(request)
    job = selectors.get_export_job(org, job_id=job_id)
    if not job:
        raise Http404(_("Export job not found."))

    return render(request, "integrations/partials/export_status.html", {"job": job})


@permission_required("integrations.export")
def export_download_view(request: HttpRequest, job_id: str) -> HttpResponse:
    """Download completed entity export file."""
    org = _get_active_org(request)
    job = selectors.get_export_job(org, job_id=job_id)
    if not job:
        raise Http404(_("Export job not found."))

    if not job.file or job.status != "completed":
        messages.error(request, _("Export file is not ready for download."))
        return redirect("integrations:exports_list")

    content_type = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if job.file_format == FileFormat.XLSX
        else "text/csv; charset=utf-8"
    )

    job.file.open("rb")
    data = job.file.read()
    job.file.close()

    response = HttpResponse(data, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{job.file_name}"'
    return response


# ---------------------------------------------------------------------------
# Webhook v1 UI Views (HTMX-enabled)
# ---------------------------------------------------------------------------


@permission_required("integrations.view")
def webhook_endpoints_list_view(request: HttpRequest) -> HttpResponse:
    """Dashboard listing configured webhook endpoints and recent delivery health."""
    org = _get_active_org(request)
    summary = selectors.get_webhooks_summary(org)
    endpoints = selectors.list_webhook_endpoints(org)
    events_by_module = list_events_by_module()

    return render(
        request,
        "integrations/webhooks/list.html",
        {
            "summary": summary,
            "endpoints": endpoints,
            "events_by_module": events_by_module,
        },
    )


@permission_required("integrations.manage")
def webhook_endpoint_create_view(request: HttpRequest) -> HttpResponse:
    """Create a new webhook destination endpoint."""
    org = _get_active_org(request)
    events_by_module = list_events_by_module()

    if request.method == "POST":
        form = WebhookEndpointForm(request.POST)
        if form.is_valid():
            endpoint = services.create_webhook_endpoint(
                organization=org,
                url=form.cleaned_data["url"],
                events=form.clean_selected_events(),
                description=form.cleaned_data.get("description", ""),
                actor=request.user,
            )
            messages.success(request, _("Webhook endpoint created successfully."))
            if request.headers.get("HX-Request"):
                res = HttpResponse()
                res["HX-Redirect"] = f"/integrations/webhooks/{endpoint.public_id}/"
                return res
            return redirect("integrations:webhook_endpoint_detail", endpoint_id=endpoint.public_id)
    else:
        form = WebhookEndpointForm()

    template = (
        "integrations/webhooks/_form_modal.html"
        if request.headers.get("HX-Request")
        else "integrations/webhooks/form.html"
    )
    return render(
        request,
        template,
        {
            "form": form,
            "events_by_module": events_by_module,
            "action": "create",
        },
    )


@permission_required("integrations.view")
def webhook_endpoint_detail_view(request: HttpRequest, endpoint_id: str) -> HttpResponse:
    """Detail view showing secret, event subscriptions, and delivery history for an endpoint."""
    org = _get_active_org(request)
    endpoint = selectors.get_webhook_endpoint(org, endpoint_id=endpoint_id)
    if not endpoint:
        raise Http404(_("Webhook endpoint not found."))

    status_filter = request.GET.get("status")
    deliveries = selectors.list_webhook_deliveries(org, endpoint=endpoint, status=status_filter)[:50]

    return render(
        request,
        "integrations/webhooks/detail.html",
        {
            "endpoint": endpoint,
            "deliveries": deliveries,
            "selected_status": status_filter,
            "events_by_module": list_events_by_module(),
        },
    )


@permission_required("integrations.manage")
def webhook_endpoint_edit_view(request: HttpRequest, endpoint_id: str) -> HttpResponse:
    """Edit URL, subscriptions, and active status of an endpoint."""
    org = _get_active_org(request)
    endpoint = selectors.get_webhook_endpoint(org, endpoint_id=endpoint_id)
    if not endpoint:
        raise Http404(_("Webhook endpoint not found."))

    events_by_module = list_events_by_module()

    if request.method == "POST":
        form = WebhookEndpointForm(request.POST, instance=endpoint)
        if form.is_valid():
            services.update_webhook_endpoint(
                endpoint=endpoint,
                url=form.cleaned_data["url"],
                events=form.clean_selected_events(),
                description=form.cleaned_data.get("description", ""),
                is_active=form.cleaned_data.get("is_active", True),
                actor=request.user,
            )
            messages.success(request, _("Webhook endpoint updated successfully."))
            if request.headers.get("HX-Request"):
                res = HttpResponse()
                res["HX-Redirect"] = f"/integrations/webhooks/{endpoint.public_id}/"
                return res
            return redirect("integrations:webhook_endpoint_detail", endpoint_id=endpoint.public_id)
    else:
        form = WebhookEndpointForm(instance=endpoint)

    template = (
        "integrations/webhooks/_form_modal.html"
        if request.headers.get("HX-Request")
        else "integrations/webhooks/form.html"
    )
    return render(
        request,
        template,
        {
            "form": form,
            "endpoint": endpoint,
            "events_by_module": events_by_module,
            "action": "edit",
        },
    )


@permission_required("integrations.manage")
def webhook_endpoint_delete_view(request: HttpRequest, endpoint_id: str) -> HttpResponse:
    """Delete a webhook endpoint."""
    org = _get_active_org(request)
    endpoint = selectors.get_webhook_endpoint(org, endpoint_id=endpoint_id)
    if not endpoint:
        raise Http404(_("Webhook endpoint not found."))

    if request.method == "POST":
        services.delete_webhook_endpoint(endpoint=endpoint, actor=request.user)
        messages.success(request, _("Webhook endpoint deleted."))
        if request.headers.get("HX-Request"):
            res = HttpResponse()
            res["HX-Redirect"] = "/integrations/webhooks/"
            return res
        return redirect("integrations:webhook_endpoints_list")

    return render(
        request,
        "integrations/webhooks/_delete_modal.html",
        {"endpoint": endpoint},
    )


@permission_required("integrations.manage")
def webhook_endpoint_rotate_secret_view(request: HttpRequest, endpoint_id: str) -> HttpResponse:
    """Regenerate secret token for an endpoint."""
    org = _get_active_org(request)
    endpoint = selectors.get_webhook_endpoint(org, endpoint_id=endpoint_id)
    if not endpoint:
        raise Http404(_("Webhook endpoint not found."))

    if request.method == "POST":
        services.rotate_webhook_secret(endpoint=endpoint, actor=request.user)
        messages.success(request, _("Signing secret rotated successfully."))

    return render(
        request,
        "integrations/webhooks/partials/_secret_panel.html",
        {"endpoint": endpoint},
    )


@permission_required("integrations.manage")
def webhook_endpoint_ping_view(request: HttpRequest, endpoint_id: str) -> HttpResponse:
    """Fire an immediate test ping delivery to verify destination connectivity."""
    org = _get_active_org(request)
    endpoint = selectors.get_webhook_endpoint(org, endpoint_id=endpoint_id)
    if not endpoint:
        raise Http404(_("Webhook endpoint not found."))

    delivery = services.send_test_ping(endpoint=endpoint, actor=request.user)

    if request.headers.get("HX-Request"):
        return render(
            request,
            "integrations/webhooks/partials/_delivery_row.html",
            {"delivery": delivery},
        )

    messages.info(request, _("Test ping dispatched. Status: %(status)s") % {"status": delivery.status})
    return redirect("integrations:webhook_endpoint_detail", endpoint_id=endpoint.public_id)


@permission_required("integrations.view")
def webhook_delivery_detail_view(request: HttpRequest, delivery_id: str) -> HttpResponse:
    """Inspect request payload, signed headers, and response transcript for a delivery."""
    org = _get_active_org(request)
    delivery = selectors.get_webhook_delivery(org, delivery_id=delivery_id)
    if not delivery:
        raise Http404(_("Webhook delivery not found."))

    template = (
        "integrations/webhooks/partials/_delivery_modal.html"
        if request.headers.get("HX-Request")
        else "integrations/webhooks/delivery_detail.html"
    )
    return render(
        request,
        template,
        {"delivery": delivery},
    )


@permission_required("integrations.manage")
def webhook_delivery_redeliver_view(request: HttpRequest, delivery_id: str) -> HttpResponse:
    """Manually re-dispatch an existing delivery payload to its endpoint."""
    org = _get_active_org(request)
    delivery = selectors.get_webhook_delivery(org, delivery_id=delivery_id)
    if not delivery:
        raise Http404(_("Webhook delivery not found."))

    services.redeliver_webhook(delivery=delivery, actor=request.user)

    if request.headers.get("HX-Request"):
        return render(
            request,
            "integrations/webhooks/partials/_delivery_row.html",
            {"delivery": delivery},
        )

    messages.success(request, _("Webhook redelivery triggered."))
    return redirect("integrations:webhook_endpoint_detail", endpoint_id=delivery.endpoint.public_id)


# =========================================================================
# Connector Framework Views
# =========================================================================


@permission_required("integrations.view")
def connections_list_view(request: HttpRequest) -> HttpResponse:
    """Gallery and active integration connections dashboard."""
    org = _get_active_org(request)
    connector_type = request.GET.get("type")
    status_filter = request.GET.get("status")

    connections = selectors.list_integration_connections(
        org,
        connector_type=connector_type,
        status=status_filter,
    )
    gallery = connector_registry.get_gallery_metadata()
    recent_logs = selectors.list_sync_logs(org, limit=10)

    return render(
        request,
        "integrations/connections_list.html",
        {
            "connections": connections,
            "gallery": gallery,
            "recent_logs": recent_logs,
            "selected_type": connector_type,
            "selected_status": status_filter,
            "connector_types": ConnectorType.choices,
        },
    )


@permission_required("integrations.manage")
def connection_create_view(
    request: HttpRequest,
    connector_type: str | None = None,
) -> HttpResponse:
    """Create a new integration connection instance."""
    org = _get_active_org(request)
    initial: dict[str, Any] = {}
    if connector_type:
        initial["connector_type"] = connector_type

    if request.method == "POST":
        form = IntegrationConnectionForm(request.POST)
        if form.is_valid():
            cleaned = form.cleaned_data
            conn = services.create_integration_connection(
                organization=org,
                name=cleaned["name"],
                connector_type=cleaned["connector_type"],
                config=form.clean_config_json(),
                credentials=form.clean_credentials_json(),
                description=cleaned.get("description", ""),
                status=cleaned.get("status"),
                sync_interval_minutes=cleaned.get("sync_interval_minutes", 60),
                actor=request.user,
            )
            messages.success(request, _("Integration connection '%(name)s' created.") % {"name": conn.name})
            return redirect("integrations:connection_detail", connection_id=conn.public_id)
    else:
        form = IntegrationConnectionForm(initial=initial)

    return render(
        request,
        "integrations/connection_form.html",
        {
            "form": form,
            "is_create": True,
            "connector_type": connector_type,
            "gallery": connector_registry.get_gallery_metadata(),
        },
    )


@permission_required("integrations.view")
def connection_detail_view(request: HttpRequest, connection_id: str) -> HttpResponse:
    """View details, sync logs, and external reference mappings for a connection."""
    org = _get_active_org(request)
    connection = selectors.get_integration_connection(org, connection_id=connection_id)
    if not connection:
        raise Http404(_("Integration connection not found."))

    sync_logs = selectors.list_sync_logs(org, connection=connection, limit=20)
    references = selectors.list_external_references(org, connection=connection)[:20]
    total_references_count = selectors.list_external_references(org, connection=connection).count()

    connector_meta = None
    try:
        connector = connector_registry.get(connection.connector_type)
        connector_meta = {
            "name": connector.name,
            "description": connector.description,
            "category": connector.category,
            "supported_actions": connector.supported_actions,
            "config_schema": connector.config_schema,
        }
    except Exception as exc:
        logger.debug("Connector metadata unavailable: %s", exc)

    return render(
        request,
        "integrations/connection_detail.html",
        {
            "connection": connection,
            "sync_logs": sync_logs,
            "references": references,
            "total_references_count": total_references_count,
            "connector_meta": connector_meta,
        },
    )


@permission_required("integrations.manage")
def connection_edit_view(request: HttpRequest, connection_id: str) -> HttpResponse:
    """Edit connection configuration and credentials."""
    org = _get_active_org(request)
    connection = selectors.get_integration_connection(org, connection_id=connection_id)
    if not connection:
        raise Http404(_("Integration connection not found."))

    if request.method == "POST":
        form = IntegrationConnectionForm(request.POST, instance=connection)
        if form.is_valid():
            cleaned = form.cleaned_data
            services.update_integration_connection(
                connection=connection,
                name=cleaned["name"],
                config=form.clean_config_json(),
                credentials=form.clean_credentials_json(),
                description=cleaned.get("description"),
                status=cleaned.get("status"),
                sync_interval_minutes=cleaned.get("sync_interval_minutes"),
                actor=request.user,
            )
            messages.success(request, _("Connection settings updated."))
            return redirect("integrations:connection_detail", connection_id=connection.public_id)
    else:
        form = IntegrationConnectionForm(instance=connection)

    return render(
        request,
        "integrations/connection_form.html",
        {
            "form": form,
            "connection": connection,
            "is_create": False,
        },
    )


@permission_required("integrations.manage")
def connection_delete_view(request: HttpRequest, connection_id: str) -> HttpResponse:
    """Delete an integration connection."""
    org = _get_active_org(request)
    connection = selectors.get_integration_connection(org, connection_id=connection_id)
    if not connection:
        raise Http404(_("Integration connection not found."))

    if request.method == "POST":
        services.delete_integration_connection(connection=connection, actor=request.user)
        messages.success(request, _("Integration connection deleted."))
        return redirect("integrations:connections_list")

    return render(
        request,
        "integrations/connection_confirm_delete.html",
        {"connection": connection},
    )


@permission_required("integrations.sync")
def connection_test_view(request: HttpRequest, connection_id: str) -> HttpResponse:
    """HTMX / POST action to test connection validity."""
    org = _get_active_org(request)
    connection = selectors.get_integration_connection(org, connection_id=connection_id)
    if not connection:
        raise Http404(_("Integration connection not found."))

    result = services.test_integration_connection(connection=connection, actor=request.user)

    if request.headers.get("HX-Request"):
        return render(
            request,
            "integrations/partials/_connection_test_result.html",
            {"result": result, "connection": connection},
        )

    if result.success:
        messages.success(request, result.message)
    else:
        messages.error(request, result.message)
    return redirect("integrations:connection_detail", connection_id=connection.public_id)


@permission_required("integrations.sync")
def connection_sync_view(request: HttpRequest, connection_id: str) -> HttpResponse:
    """HTMX / POST action to trigger manual synchronization."""
    org = _get_active_org(request)
    connection = selectors.get_integration_connection(org, connection_id=connection_id)
    if not connection:
        raise Http404(_("Integration connection not found."))

    direction = request.POST.get("direction", "inbound")
    log, result = services.run_integration_sync(
        connection=connection,
        direction=direction,
        actor=request.user,
    )

    if request.headers.get("HX-Request"):
        return render(
            request,
            "integrations/partials/_connection_sync_result.html",
            {"log": log, "result": result, "connection": connection},
        )

    if result.success:
        messages.success(request, result.message)
    else:
        messages.error(request, result.message)
    return redirect("integrations:connection_detail", connection_id=connection.public_id)


@permission_required("integrations.view")
def external_references_list_view(request: HttpRequest) -> HttpResponse:
    """List external entity reference mappings."""
    org = _get_active_org(request)
    entity_filter = request.GET.get("entity_type")
    references = selectors.list_external_references(org, entity_type=entity_filter)[:100]

    return render(
        request,
        "integrations/external_references_list.html",
        {
            "references": references,
            "selected_entity": entity_filter,
        },
    )


# --- OAuth Application Views ---


@permission_required("integrations.view")
def oauth_applications_list_view(request: HttpRequest) -> HttpResponse:
    """List registered OAuth2 applications for the tenant."""
    org = _get_active_org(request)
    applications = selectors.list_oauth_applications(org)
    return render(
        request,
        "integrations/oauth_applications_list.html",
        {"applications": applications},
    )


@permission_required("integrations.oauth_manage")
def oauth_application_create_view(request: HttpRequest) -> HttpResponse:
    """Register a new OAuth2 client application."""
    org = _get_active_org(request)

    if request.method == "POST":
        form = OAuthApplicationForm(request.POST)
        if form.is_valid():
            scopes_str = form.clean_scopes()
            app, raw_secret = services.create_oauth_application(
                organization=org,
                name=form.cleaned_data["name"],
                client_type=form.cleaned_data["client_type"],
                authorization_grant_type=form.cleaned_data["authorization_grant_type"],
                redirect_uris=form.cleaned_data.get("redirect_uris", ""),
                allowed_scopes=scopes_str,
                description=form.cleaned_data.get("description", ""),
                skip_authorization=form.cleaned_data.get("skip_authorization", False),
                actor=request.user,
            )
            return render(
                request,
                "integrations/oauth_application_created.html",
                {
                    "application": app,
                    "raw_secret": raw_secret,
                },
            )
    else:
        form = OAuthApplicationForm()

    return render(
        request,
        "integrations/oauth_application_form.html",
        {"form": form, "is_new": True},
    )


@permission_required("integrations.view")
def oauth_application_detail_view(request: HttpRequest, app_id: str) -> HttpResponse:
    """View details and configuration of an OAuth application."""
    org = _get_active_org(request)
    app = selectors.get_oauth_application(org, application_id=app_id)
    if not app:
        raise Http404(_("OAuth application not found."))

    return render(
        request,
        "integrations/oauth_application_detail.html",
        {"application": app},
    )


@permission_required("integrations.oauth_manage")
def oauth_application_edit_view(request: HttpRequest, app_id: str) -> HttpResponse:
    """Edit settings on an OAuth application."""
    org = _get_active_org(request)
    app = selectors.get_oauth_application(org, application_id=app_id)
    if not app:
        raise Http404(_("OAuth application not found."))

    if request.method == "POST":
        form = OAuthApplicationForm(request.POST, instance=app)
        if form.is_valid():
            scopes_str = form.clean_scopes()
            services.update_oauth_application(
                application=app,
                name=form.cleaned_data["name"],
                client_type=form.cleaned_data["client_type"],
                authorization_grant_type=form.cleaned_data["authorization_grant_type"],
                redirect_uris=form.cleaned_data.get("redirect_uris", ""),
                allowed_scopes=scopes_str,
                description=form.cleaned_data.get("description", ""),
                skip_authorization=form.cleaned_data.get("skip_authorization", False),
                actor=request.user,
            )
            messages.success(request, _("OAuth application updated successfully."))
            return redirect("integrations:oauth_application_detail", app_id=app.public_id)
    else:
        form = OAuthApplicationForm(instance=app)

    return render(
        request,
        "integrations/oauth_application_form.html",
        {"form": form, "application": app, "is_new": False},
    )


@permission_required("integrations.oauth_manage")
def oauth_application_delete_view(request: HttpRequest, app_id: str) -> HttpResponse:
    """Delete an OAuth application and revoke tokens."""
    org = _get_active_org(request)
    app = selectors.get_oauth_application(org, application_id=app_id)
    if not app:
        raise Http404(_("OAuth application not found."))

    if request.method == "POST":
        services.delete_oauth_application(application=app, actor=request.user)
        messages.success(request, _("OAuth application deleted."))
        return redirect("integrations:oauth_applications_list")

    return render(
        request,
        "integrations/oauth_application_confirm_delete.html",
        {"application": app},
    )


@permission_required("integrations.oauth_manage")
def oauth_application_rotate_secret_view(request: HttpRequest, app_id: str) -> HttpResponse:
    """Rotate secret for an OAuth application."""
    if request.method != "POST":
        raise Http404(_("Method not allowed"))
    org = _get_active_org(request)
    app = selectors.get_oauth_application(org, application_id=app_id)
    if not app:
        raise Http404(_("OAuth application not found."))

    new_secret = services.rotate_oauth_client_secret(application=app, actor=request.user)

    if request.headers.get("HX-Request"):
        return render(
            request,
            "integrations/partials/_oauth_secret_result.html",
            {"new_secret": new_secret, "application": app},
        )
    messages.success(request, _("Client secret rotated. New secret: %s") % new_secret)
    return redirect("integrations:oauth_application_detail", app_id=app.public_id)


def oauth_authorized_tokens_list_view(request: HttpRequest) -> HttpResponse:
    """User-facing view of authorized third-party applications."""
    if not request.user.is_authenticated:
        raise PermissionDenied
    org = _get_active_org(request)
    tokens = selectors.list_user_authorized_tokens(request.user, org)

    return render(
        request,
        "integrations/oauth_authorized_tokens.html",
        {"tokens": tokens},
    )


def oauth_revoke_token_view(request: HttpRequest, token_id: int) -> HttpResponse:
    """Revoke user authorization for a token."""
    if request.method != "POST" or not request.user.is_authenticated:
        raise PermissionDenied
    org = _get_active_org(request)
    services.revoke_user_oauth_token(
        token_id=token_id, user=request.user, organization=org, actor=request.user
    )
    messages.success(request, _("Application access revoked."))
    return redirect("integrations:oauth_authorized_tokens")


# --- Inbound Webhook Views ---


@permission_required("integrations.view")
def inbound_endpoints_list_view(request: HttpRequest) -> HttpResponse:
    """List inbound webhook receiver endpoints."""
    org = _get_active_org(request)
    endpoints = selectors.list_inbound_webhook_endpoints(org)

    return render(
        request,
        "integrations/inbound_endpoints_list.html",
        {"endpoints": endpoints},
    )


@permission_required("integrations.inbound_manage")
def inbound_endpoint_create_view(request: HttpRequest) -> HttpResponse:
    """Create a new inbound webhook endpoint."""
    org = _get_active_org(request)

    if request.method == "POST":
        form = InboundWebhookEndpointForm(request.POST)
        if form.is_valid():
            secret_val = form.cleaned_data.get("custom_secret") or None
            endpoint = services.create_inbound_webhook_endpoint(
                organization=org,
                name=form.cleaned_data["name"],
                provider=form.cleaned_data["provider"],
                signature_header=form.cleaned_data.get("signature_header", "X-Signature"),
                signature_algorithm=form.cleaned_data.get("signature_algorithm", "hmac_sha256"),
                secret=secret_val,
                target_event=form.cleaned_data.get("target_event", "inbound_webhook.received"),
                description=form.cleaned_data.get("description", ""),
                actor=request.user,
            )
            messages.success(request, _("Inbound webhook endpoint created successfully."))
            return redirect("integrations:inbound_endpoint_detail", endpoint_id=endpoint.public_id)
    else:
        form = InboundWebhookEndpointForm()

    return render(
        request,
        "integrations/inbound_endpoint_form.html",
        {"form": form, "is_new": True},
    )


@permission_required("integrations.view")
def inbound_endpoint_detail_view(request: HttpRequest, endpoint_id: str) -> HttpResponse:
    """View details, receipt URL, curl sample, and recent logs for an inbound webhook."""
    org = _get_active_org(request)
    endpoint = selectors.get_inbound_webhook_endpoint(org, endpoint_id=endpoint_id)
    if not endpoint:
        raise Http404(_("Inbound webhook endpoint not found."))

    logs = selectors.list_inbound_webhook_logs(org, endpoint=endpoint, limit=30)
    receive_url = request.build_absolute_uri(
        reverse("api:inbound-webhook-receive", kwargs={"public_id": endpoint.public_id})
    )

    return render(
        request,
        "integrations/inbound_endpoint_detail.html",
        {
            "endpoint": endpoint,
            "logs": logs,
            "receive_url": receive_url,
        },
    )


@permission_required("integrations.inbound_manage")
def inbound_endpoint_edit_view(request: HttpRequest, endpoint_id: str) -> HttpResponse:
    """Edit settings on an inbound webhook endpoint."""
    org = _get_active_org(request)
    endpoint = selectors.get_inbound_webhook_endpoint(org, endpoint_id=endpoint_id)
    if not endpoint:
        raise Http404(_("Inbound webhook endpoint not found."))

    if request.method == "POST":
        form = InboundWebhookEndpointForm(request.POST, instance=endpoint)
        if form.is_valid():
            custom_sec = form.cleaned_data.get("custom_secret")
            if custom_sec and custom_sec != endpoint.secret:
                endpoint.secret = custom_sec
            services.update_inbound_webhook_endpoint(
                endpoint=endpoint,
                name=form.cleaned_data["name"],
                provider=form.cleaned_data["provider"],
                signature_header=form.cleaned_data.get("signature_header", "X-Signature"),
                signature_algorithm=form.cleaned_data.get("signature_algorithm", "hmac_sha256"),
                target_event=form.cleaned_data.get("target_event", "inbound_webhook.received"),
                status=form.cleaned_data.get("status", "active"),
                description=form.cleaned_data.get("description", ""),
                actor=request.user,
            )
            messages.success(request, _("Inbound webhook endpoint updated."))
            return redirect("integrations:inbound_endpoint_detail", endpoint_id=endpoint.public_id)
    else:
        form = InboundWebhookEndpointForm(instance=endpoint)

    return render(
        request,
        "integrations/inbound_endpoint_form.html",
        {"form": form, "endpoint": endpoint, "is_new": False},
    )


@permission_required("integrations.inbound_manage")
def inbound_endpoint_delete_view(request: HttpRequest, endpoint_id: str) -> HttpResponse:
    """Delete an inbound webhook endpoint."""
    org = _get_active_org(request)
    endpoint = selectors.get_inbound_webhook_endpoint(org, endpoint_id=endpoint_id)
    if not endpoint:
        raise Http404(_("Inbound webhook endpoint not found."))

    if request.method == "POST":
        services.delete_inbound_webhook_endpoint(endpoint=endpoint, actor=request.user)
        messages.success(request, _("Inbound webhook endpoint deleted."))
        return redirect("integrations:inbound_endpoints_list")

    return render(
        request,
        "integrations/inbound_endpoint_confirm_delete.html",
        {"endpoint": endpoint},
    )


@permission_required("integrations.inbound_manage")
def inbound_endpoint_rotate_secret_view(request: HttpRequest, endpoint_id: str) -> HttpResponse:
    """Rotate signing secret for an inbound endpoint."""
    if request.method != "POST":
        raise Http404(_("Method not allowed"))
    org = _get_active_org(request)
    endpoint = selectors.get_inbound_webhook_endpoint(org, endpoint_id=endpoint_id)
    if not endpoint:
        raise Http404(_("Inbound webhook endpoint not found."))

    new_secret = services.rotate_inbound_webhook_secret(endpoint=endpoint, actor=request.user)

    if request.headers.get("HX-Request"):
        return render(
            request,
            "integrations/partials/_inbound_secret_result.html",
            {"new_secret": new_secret, "endpoint": endpoint},
        )
    messages.success(request, _("Secret rotated. New secret: %s") % new_secret)
    return redirect("integrations:inbound_endpoint_detail", endpoint_id=endpoint.public_id)


@permission_required("integrations.view")
def inbound_logs_list_view(request: HttpRequest) -> HttpResponse:
    """Global audit log of inbound webhook events received across all endpoints."""
    org = _get_active_org(request)
    v_status = request.GET.get("status")
    logs = selectors.list_inbound_webhook_logs(org, verification_status=v_status, limit=100)

    return render(
        request,
        "integrations/inbound_logs_list.html",
        {"logs": logs, "selected_status": v_status},
    )


# ---------------------------------------------------------------------------
# Data Portability (Full Tenant Export / Import)
# ---------------------------------------------------------------------------


@permission_required("integrations.portability_manage")
def portability_overview_view(request: HttpRequest) -> HttpResponse:
    """Dashboard showing full-tenant backup export and import jobs."""
    org = _get_active_org(request)
    exports = selectors.list_tenant_export_jobs(org)
    imports = selectors.list_tenant_import_jobs(org)

    return render(
        request,
        "integrations/portability_overview.html",
        {
            "exports": exports,
            "imports": imports,
        },
    )


@permission_required("integrations.portability_manage")
def tenant_export_create_view(request: HttpRequest) -> HttpResponse:
    """Initiate a full-tenant data backup export job."""
    org = _get_active_org(request)

    if request.method == "POST":
        form = TenantExportJobForm(request.POST)
        if form.is_valid():
            include_audit = form.cleaned_data.get("include_audit_logs", True)
            job = services.create_tenant_export_job(
                org=org,
                actor=request.user,
                include_audit_logs=include_audit,
            )
            # Process synchronously in simple environments or dispatch to celery
            try:
                from apps.integrations.tasks import export_tenant_data_task

                export_tenant_data_task.delay(str(job.public_id))
            except Exception:
                services.process_tenant_export_job(job)

            messages.success(request, _("Tenant export job created and queued for packaging."))
            return redirect("integrations:portability_overview")
    else:
        form = TenantExportJobForm()

    return render(
        request,
        "integrations/tenant_export_form.html",
        {"form": form},
    )


@permission_required("integrations.portability_manage")
def tenant_export_download_view(request: HttpRequest, job_id: str) -> HttpResponse:
    """Download the completed tenant backup archive."""
    org = _get_active_org(request)
    job = selectors.get_tenant_export_job(org, job_id=job_id)
    if not job or not job.file:
        raise Http404(_("Tenant export archive not found or not ready."))

    response = FileResponse(job.file.open("rb"), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="tenant-export-{org.slug}-{job.public_id}.zip"'
    return response


@permission_required("integrations.portability_manage")
def tenant_import_create_view(request: HttpRequest) -> HttpResponse:
    """Upload a full-tenant backup archive to validate and import."""
    org = _get_active_org(request)

    if request.method == "POST":
        form = TenantImportJobForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded = form.cleaned_data["file"]
            job = services.create_tenant_import_job(
                org=org,
                file=uploaded,
                actor=request.user,
            )
            try:
                from apps.integrations.tasks import validate_tenant_import_task

                validate_tenant_import_task.delay(str(job.public_id))
            except Exception:
                services.validate_tenant_import_job(job)

            messages.success(request, _("Backup uploaded. Validation in progress."))
            return redirect("integrations:tenant_import_detail", job_id=job.public_id)
    else:
        form = TenantImportJobForm()

    return render(
        request,
        "integrations/tenant_import_form.html",
        {"form": form},
    )


@permission_required("integrations.portability_manage")
def tenant_import_detail_view(request: HttpRequest, job_id: str) -> HttpResponse:
    """View validation status and details of an uploaded tenant backup."""
    org = _get_active_org(request)
    job = selectors.get_tenant_import_job(org, job_id=job_id)
    if not job:
        raise Http404(_("Tenant import job not found."))

    return render(
        request,
        "integrations/tenant_import_detail.html",
        {"job": job},
    )


@permission_required("integrations.portability_manage")
def tenant_import_commit_view(request: HttpRequest, job_id: str) -> HttpResponse:
    """Commit the validated tenant backup archive."""
    if request.method != "POST":
        raise Http404(_("Method not allowed"))
    org = _get_active_org(request)
    job = selectors.get_tenant_import_job(org, job_id=job_id)
    if not job:
        raise Http404(_("Tenant import job not found."))

    try:
        from apps.integrations.tasks import commit_tenant_import_task

        commit_tenant_import_task.delay(str(job.public_id))
    except Exception:
        services.commit_tenant_import_job(job)

    messages.success(request, _("Import commit initiated."))
    return redirect("integrations:tenant_import_detail", job_id=job.public_id)


# ---------------------------------------------------------------------------
# Data Retention Policy & Cleanup
# ---------------------------------------------------------------------------


@permission_required("integrations.retention_manage")
def retention_policy_view(request: HttpRequest) -> HttpResponse:
    """View and update data retention policies for the tenant."""
    org = _get_active_org(request)
    policy = selectors.get_retention_policy(org)

    if request.method == "POST":
        form = DataRetentionPolicyForm(request.POST, instance=policy)
        if form.is_valid():
            services.configure_data_retention_policy(
                org=org,
                audit_log_retention_days=form.cleaned_data["audit_log_retention_days"],
                webhook_log_retention_days=form.cleaned_data["webhook_log_retention_days"],
                sync_log_retention_days=form.cleaned_data["sync_log_retention_days"],
                export_file_retention_days=form.cleaned_data["export_file_retention_days"],
                is_active=form.cleaned_data["is_active"],
                actor=request.user,
            )
            messages.success(request, _("Data retention policy updated successfully."))
            return redirect("integrations:retention_policy")
    else:
        form = DataRetentionPolicyForm(instance=policy)

    return render(
        request,
        "integrations/retention_policy.html",
        {"form": form, "policy": policy},
    )


@permission_required("integrations.retention_manage")
def retention_cleanup_trigger_view(request: HttpRequest) -> HttpResponse:
    """Trigger data retention cleanup now."""
    if request.method != "POST":
        raise Http404(_("Method not allowed"))
    org = _get_active_org(request)

    res = services.execute_data_retention_cleanup(org=org)
    total = sum(res.values())

    if request.headers.get("HX-Request"):
        return render(
            request,
            "integrations/partials/_retention_cleanup_result.html",
            {"results": res, "total_cleaned": total},
        )

    messages.success(
        request,
        _("Retention cleanup complete: %(total)s old records purged.") % {"total": total},
    )
    return redirect("integrations:retention_policy")


# ---------------------------------------------------------------------------
# GDPR & Privacy (Subject Access Requests & Erasure)
# ---------------------------------------------------------------------------


@permission_required("integrations.privacy_manage")
def data_subject_requests_list_view(request: HttpRequest) -> HttpResponse:
    """List GDPR Right to Access and Right to Erasure requests."""
    org = _get_active_org(request)
    requests_qs = selectors.list_data_subject_requests(org)

    return render(
        request,
        "integrations/privacy_requests_list.html",
        {"requests": requests_qs},
    )


@permission_required("integrations.privacy_manage")
def data_subject_request_create_view(request: HttpRequest) -> HttpResponse:
    """Submit a new GDPR SAR or Erasure request."""
    org = _get_active_org(request)

    if request.method == "POST":
        form = DataSubjectRequestForm(request.POST)
        if form.is_valid():
            req_obj = services.create_data_subject_request(
                org=org,
                subject_email=form.cleaned_data["subject_email"],
                request_type=form.cleaned_data["request_type"],
                subject_name=form.cleaned_data.get("subject_name", ""),
                subject_type=form.cleaned_data.get("subject_type", "customer"),
                reason=form.cleaned_data.get("reason", ""),
                verification_notes=form.cleaned_data.get("verification_notes", ""),
                actor=request.user,
            )
            messages.success(request, _("Data subject request registered."))
            return redirect("integrations:privacy_request_detail", request_id=req_obj.public_id)
    else:
        form = DataSubjectRequestForm()

    return render(
        request,
        "integrations/privacy_request_form.html",
        {"form": form},
    )


@permission_required("integrations.privacy_manage")
def data_subject_request_detail_view(request: HttpRequest, request_id: str) -> HttpResponse:
    """View details, verification status, and execute GDPR request."""
    org = _get_active_org(request)
    req_obj = selectors.get_data_subject_request(org, request_id=request_id)
    if not req_obj:
        raise Http404(_("Data subject request not found."))

    return render(
        request,
        "integrations/privacy_request_detail.html",
        {"dsr": req_obj},
    )


@permission_required("integrations.privacy_manage")
def data_subject_request_execute_view(request: HttpRequest, request_id: str) -> HttpResponse:
    """Execute processing of GDPR SAR export or Erasure."""
    if request.method != "POST":
        raise Http404(_("Method not allowed"))
    org = _get_active_org(request)
    req_obj = selectors.get_data_subject_request(org, request_id=request_id)
    if not req_obj:
        raise Http404(_("Data subject request not found."))

    try:
        from apps.integrations.tasks import execute_data_subject_request_task

        execute_data_subject_request_task.delay(str(req_obj.public_id))
    except Exception:
        from apps.integrations.models import DataSubjectRequestType

        if req_obj.request_type == DataSubjectRequestType.ACCESS_EXPORT:
            services.process_data_subject_access_request(req_obj)
        elif req_obj.request_type == DataSubjectRequestType.ERASURE:
            services.process_data_subject_erasure(req_obj)

    messages.success(request, _("GDPR request execution initiated."))
    return redirect("integrations:privacy_request_detail", request_id=req_obj.public_id)


@permission_required("integrations.privacy_manage")
def data_subject_sar_download_view(request: HttpRequest, request_id: str) -> HttpResponse:
    """Download the exported SAR JSON file."""
    org = _get_active_org(request)
    req_obj = selectors.get_data_subject_request(org, request_id=request_id)
    if not req_obj or not req_obj.export_file:
        raise Http404(_("SAR export file not found."))

    response = FileResponse(req_obj.export_file.open("rb"), content_type="application/json")
    response["Content-Disposition"] = f'attachment; filename="sar-{req_obj.public_id}.json"'
    return response

