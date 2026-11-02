"""Read-only selectors for Point of Sale (POS) operations."""

from __future__ import annotations

import ctypes
import json
import logging
import platform
import shutil
import subprocess
from ctypes import wintypes
from decimal import Decimal
from typing import Any

from django.db.models import DecimalField, F, OuterRef, Q, QuerySet, Subquery, Value
from django.db.models.functions import Coalesce

from apps.catalog.models import Category, Product
from apps.inventory.models import StockLevel
from apps.pos.models import (
    POSHeldCart,
    POSRegister,
    POSSale,
    POSShift,
    POSShiftStatus,
)
from apps.sales.models import PaymentMethod, PaymentProcessMode
from apps.tenancy.models import Organization, Warehouse

logger = logging.getLogger(__name__)


def list_registers(
    *,
    organization: Organization,
    branch_id: int | None = None,
    is_active: bool | None = None,
) -> QuerySet[POSRegister]:
    """List POS registers scoped by tenant organization."""
    qs = POSRegister.all_tenants.filter(organization=organization).select_related("branch", "warehouse")
    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    if is_active is not None:
        qs = qs.filter(is_active=is_active)
    return qs.order_by("code")


def get_register(
    *,
    organization: Organization,
    register_id: int | None = None,
    public_id: str | None = None,
) -> POSRegister | None:
    """Fetch single POS register by primary key or public_id."""
    qs = POSRegister.all_tenants.filter(organization=organization).select_related("branch", "warehouse")
    if register_id:
        return qs.filter(pk=register_id).first()
    if public_id:
        return qs.filter(public_id=public_id).first()
    return None


def get_open_shift_for_register(
    *,
    organization: Organization,
    register: POSRegister,
) -> POSShift | None:
    """Get the currently open shift on a register if any."""
    return (
        POSShift.all_tenants.filter(
            organization=organization,
            register=register,
            status=POSShiftStatus.OPEN,
        )
        .select_related("register", "cashier")
        .first()
    )


def get_active_shift_for_user(
    *,
    organization: Organization,
    user: Any,
) -> POSShift | None:
    """Get the cashier's active open shift if any."""
    return (
        POSShift.all_tenants.filter(
            organization=organization,
            cashier=user,
            status=POSShiftStatus.OPEN,
        )
        .select_related("register", "cashier")
        .first()
    )


def list_shifts(
    *,
    organization: Organization,
    register_id: int | None = None,
    cashier_id: int | None = None,
    status: str | None = None,
) -> QuerySet[POSShift]:
    """List cashier shifts with filters."""
    qs = POSShift.all_tenants.filter(organization=organization).select_related("register", "cashier")
    if register_id:
        qs = qs.filter(register_id=register_id)
    if cashier_id:
        qs = qs.filter(cashier_id=cashier_id)
    if status:
        qs = qs.filter(status=status)
    return qs.order_by("-opened_at")


def get_shift(
    *,
    organization: Organization,
    shift_id: int | None = None,
    public_id: str | None = None,
) -> POSShift | None:
    """Fetch a single POS shift."""
    qs = POSShift.all_tenants.filter(organization=organization).select_related(
        "register", "cashier", "variance_journal_entry"
    )
    if shift_id:
        return qs.filter(pk=shift_id).first()
    if public_id:
        return qs.filter(public_id=public_id).first()
    return None


def list_sales(
    *,
    organization: Organization,
    shift_id: int | None = None,
    register_id: int | None = None,
    search: str | None = None,
) -> QuerySet[POSSale]:
    """List completed POS sales."""
    qs = POSSale.all_tenants.filter(organization=organization).select_related(
        "shift", "register", "cashier", "customer", "invoice"
    )
    if shift_id:
        qs = qs.filter(shift_id=shift_id)
    if register_id:
        qs = qs.filter(register_id=register_id)
    if search:
        qs = qs.filter(
            Q(receipt_number__icontains=search)
            | Q(customer__name__icontains=search)
            | Q(invoice__invoice_number__icontains=search)
        )
    return qs.order_by("-created_at")


def get_sale(
    *,
    organization: Organization,
    sale_id: int | None = None,
    public_id: str | None = None,
) -> POSSale | None:
    """Fetch a single completed POS sale with invoice and line items."""
    qs = POSSale.all_tenants.filter(organization=organization).select_related(
        "shift", "register", "cashier", "customer", "invoice"
    )
    if sale_id:
        return qs.filter(pk=sale_id).first()
    if public_id:
        return qs.filter(public_id=public_id).first()
    return None


def list_held_carts(
    *,
    organization: Organization,
    shift_id: int,
) -> QuerySet[POSHeldCart]:
    """List parked/held carts for a given shift."""
    return (
        POSHeldCart.all_tenants.filter(
            organization=organization,
            shift_id=shift_id,
        )
        .select_related("customer")
        .order_by("-created_at")
    )


def get_pos_catalog_products(
    *,
    organization: Organization,
    search: str | None = None,
    category_id: int | None = None,
    warehouse: Warehouse | None = None,
) -> QuerySet[Product]:
    """Fetch active products for the POS touch grid and barcode lookup, with warehouse stock levels."""
    qs = Product.all_tenants.filter(
        organization=organization,
        is_active=True,
    ).select_related("category", "unit", "tax_code").prefetch_related("images")

    if warehouse:
        stock_subquery = (
            StockLevel.all_tenants.filter(
                organization=organization,
                product=OuterRef("pk"),
                warehouse=warehouse,
            )
            .annotate(avail=F("on_hand") - F("reserved"))
            .values("avail")[:1]
        )
        qs = qs.annotate(
            stock_qty=Coalesce(
                Subquery(stock_subquery),
                Value(Decimal("0.0000")),
                output_field=DecimalField(max_digits=18, decimal_places=4),
            )
        )

    if category_id:
        qs = qs.filter(category_id=category_id)
    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(sku__icontains=search) | Q(barcode__icontains=search))
    return qs.order_by("name")[:100]


def get_pos_categories(
    *,
    organization: Organization,
) -> QuerySet[Category]:
    """Fetch active categories for POS quick filter buttons."""
    return Category.all_tenants.filter(
        organization=organization,
        is_active=True,
    ).order_by("name")


def _parse_printer_type(port: str) -> tuple[str, str]:
    port_lower = port.lower()
    if any(k in port_lower for k in ("wsd", "tcp", "ip", "net")):
        return "wifi", "Wi-Fi"
    if "usb" in port_lower:
        return "usb", "USB"
    return "cable", "Cable"


def _enum_printers_winspool() -> list[dict[str, Any]]:
    """Discover real physical/network printers on Windows via winspool EnumPrintersW."""
    virtual_keywords = ("pdf", "xps", "onenote", "fax", "anydesk", "document writer")
    try:
        winspool = ctypes.WinDLL("winspool.drv")
        flags = 0x00000002 | 0x00000004  # PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS

        class PRINTER_INFO_2(ctypes.Structure):  # noqa: N801
            _fields_ = [
                ("pServerName", wintypes.LPWSTR),
                ("pPrinterName", wintypes.LPWSTR),
                ("pShareName", wintypes.LPWSTR),
                ("pPortName", wintypes.LPWSTR),
                ("pDriverName", wintypes.LPWSTR),
                ("pComment", wintypes.LPWSTR),
                ("pLocation", wintypes.LPWSTR),
                ("pDevMode", ctypes.c_void_p),
                ("pSepFile", wintypes.LPWSTR),
                ("pPrintProcessor", wintypes.LPWSTR),
                ("pDatatype", wintypes.LPWSTR),
                ("pParameters", wintypes.LPWSTR),
                ("pSecurityDescriptor", ctypes.c_void_p),
                ("Attributes", wintypes.DWORD),
                ("Priority", wintypes.DWORD),
                ("DefaultPriority", wintypes.DWORD),
                ("StartTime", wintypes.DWORD),
                ("UntilTime", wintypes.DWORD),
                ("Status", wintypes.DWORD),
                ("cJobs", wintypes.DWORD),
                ("AveragePPM", wintypes.DWORD),
            ]

        needed = wintypes.DWORD()
        returned = wintypes.DWORD()
        winspool.EnumPrintersW(flags, None, 2, None, 0, ctypes.byref(needed), ctypes.byref(returned))
        if needed.value > 0:
            buf = ctypes.create_string_buffer(needed.value)
            if winspool.EnumPrintersW(flags, None, 2, buf, needed.value, ctypes.byref(needed), ctypes.byref(returned)):
                items = ctypes.cast(buf, ctypes.POINTER(PRINTER_INFO_2))
                fast_printers: list[dict[str, Any]] = []
                for i in range(returned.value):
                    p = items[i]
                    name = p.pPrinterName or ""
                    driver = p.pDriverName or ""
                    port = p.pPortName or ""
                    if any(vk in name.lower() or vk in driver.lower() for vk in virtual_keywords):
                        continue
                    ptype, badge = _parse_printer_type(port)
                    fast_printers.append({
                        "id": name,
                        "name": name,
                        "type": ptype,
                        "badge": badge,
                        "port": port,
                        "driver": driver,
                    })
                return fast_printers
    except Exception as exc:
        logger.debug("Winspool EnumPrintersW fast path error: %s", exc)
    return []


def _get_windows_printers() -> list[dict[str, Any]]:
    """Discover real physical/network printers on Windows."""
    printers = _enum_printers_winspool()
    if printers:
        return printers

    virtual_keywords = ("pdf", "xps", "onenote", "fax", "anydesk", "document writer")
    cmd = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "Get-Printer | Select-Object Name, Type, DriverName, PortName, PrinterStatus | ConvertTo-Json -Compress",
    ]
    printers_out: list[dict[str, Any]] = []
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=8, check=False)  # noqa: S603
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout)
            if isinstance(data, dict):
                data = [data]
            for p in data:
                name = p.get("Name") or ""
                driver = p.get("DriverName") or ""
                port = p.get("PortName") or ""
                if any(vk in name.lower() or vk in driver.lower() for vk in virtual_keywords):
                    continue
                ptype, badge = _parse_printer_type(port)
                printers_out.append({
                    "id": name,
                    "name": name,
                    "type": ptype,
                    "badge": badge,
                    "port": port,
                    "driver": driver,
                })
    except Exception as exc:
        logger.debug("Windows printer discovery error: %s", exc)
    return printers_out


def _get_unix_printers() -> list[dict[str, Any]]:
    lpstat_bin = shutil.which("lpstat")
    if not lpstat_bin:
        return []
    printers: list[dict[str, Any]] = []
    try:
        res = subprocess.run([lpstat_bin, "-p"], capture_output=True, text=True, timeout=5, check=False)  # noqa: S603
        for line in res.stdout.splitlines():
            if line.startswith("printer "):
                pname = line.split()[1]
                printers.append({
                    "id": pname,
                    "name": pname,
                    "type": "network",
                    "badge": "Network",
                    "port": "",
                    "driver": "",
                })
    except Exception as exc:
        logger.debug("Unix printer discovery error: %s", exc)
    return printers


def get_system_printers() -> list[dict[str, Any]]:
    """Discover real physical/network printers connected to the host system.

    Filters out virtual software drivers (OneNote, XPS, Fax, PDF printers)
    and identifies connection type: 'wifi' (WSD / TCP/IP), 'usb' (USB port),
    or 'cable' / 'network'.
    """
    sys_name = platform.system()
    if sys_name == "Windows":
        return _get_windows_printers()
    if sys_name in ("Linux", "Darwin"):
        return _get_unix_printers()
    return []


def list_active_payment_methods(*, organization: Organization) -> list[dict[str, Any]]:
    """List active payment methods configured for this tenant organization."""
    methods = list(
        PaymentMethod.all_tenants.filter(organization=organization, is_active=True).order_by("sort_order", "name")
    )
    if not methods:
        defaults = [
            {"name": "Cash", "code": "cash", "process_mode": PaymentProcessMode.RECORD_ONLY, "is_default": True, "sort_order": 1},
            {"name": "Card", "code": "card", "process_mode": PaymentProcessMode.RECORD_ONLY, "is_default": False, "sort_order": 2},
            {"name": "Mobile Pay", "code": "mobile_pay", "process_mode": PaymentProcessMode.RECORD_ONLY, "is_default": False, "sort_order": 3},
            {"name": "Bank Transfer", "code": "bank_transfer", "process_mode": PaymentProcessMode.RECORD_ONLY, "is_default": False, "sort_order": 4},
        ]
        methods = []
        for d in defaults:
            pm, _ = PaymentMethod.all_tenants.get_or_create(
                organization=organization,
                code=d["code"],
                defaults=d,
            )
            methods.append(pm)

    return [
        {
            "id": pm.pk,
            "code": pm.code,
            "name": pm.name,
            "process_mode": pm.process_mode,
            "is_default": pm.is_default,
        }
        for pm in methods
    ]
