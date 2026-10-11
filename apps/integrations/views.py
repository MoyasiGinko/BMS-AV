"""Views for data imports (validate-preview-commit), entity exports, and templates."""

from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from apps.core.event_catalog import list_events_by_module
from apps.core.permissions import permission_required
from apps.integrations import selectors, services
from apps.integrations.forms import WebhookEndpointForm
from apps.integrations.importers import get_importer
from apps.integrations.models import (
    EntityType,
    FileFormat,
    ImportJobStatus,
)
from apps.tenancy.models import Organization


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
