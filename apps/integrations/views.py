"""Views for data imports (validate-preview-commit), entity exports, and templates."""

from __future__ import annotations

import logging
from typing import Any

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from apps.core.event_catalog import list_events_by_module
from apps.core.permissions import permission_required
from apps.integrations import selectors, services
from apps.integrations.connectors import connector_registry
from apps.integrations.forms import IntegrationConnectionForm, WebhookEndpointForm
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
