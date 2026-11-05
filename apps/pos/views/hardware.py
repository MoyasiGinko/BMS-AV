from __future__ import annotations

import contextlib
import json
import threading

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import permission_required
from apps.pos import printing, selectors
from apps.pos.views.common import _get_org


@permission_required("pos.access")
def printers_view(request: HttpRequest) -> HttpResponse:
    """Return live system printers for POS terminal."""
    printers = selectors.get_system_printers()
    return JsonResponse({"printers": printers})


@permission_required("pos.access")
def scanners_view(request: HttpRequest) -> HttpResponse:
    """Return live system barcode scanners for POS terminal."""
    scanners = selectors.get_system_scanners()
    return JsonResponse({"scanners": scanners})


def _extract_printer_name(request: HttpRequest) -> str:
    name = request.GET.get("printer_name") or request.POST.get("printer_name") or ""
    if not name and request.content_type == "application/json":
        with contextlib.suppress(Exception):
            name = json.loads(request.body.decode("utf-8")).get("printer_name", "")
    return name


@permission_required("pos.access")
def test_printer_action(request: HttpRequest) -> HttpResponse:
    """Send a test print slip directly to the chosen OS hardware printer."""
    printer_name = _extract_printer_name(request)
    if not printer_name:
        return JsonResponse({"success": False, "error": str(_("No printer specified."))}, status=400)
    threading.Thread(
        target=printing.spool_test_slip_to_printer,
        kwargs={"organization": _get_org(request), "printer_name": printer_name},
        daemon=True,
    ).start()
    return JsonResponse({"success": True, "printer_name": printer_name})


@permission_required("pos.access")
def open_drawer_action(request: HttpRequest) -> HttpResponse:
    """Trigger the cash drawer / locker to kick open via printer kick pulse."""
    printer_name = _extract_printer_name(request)
    success = printing.open_cash_drawer(printer_name=printer_name)
    return JsonResponse({"success": success, "drawer_opened": True})
