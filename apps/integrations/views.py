"""Views for data imports (validate-preview-commit), entity exports, and templates."""

from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from apps.core.permissions import permission_required
from apps.integrations import selectors, services
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
