"""Hardware printer spooling services for the Point of Sale (POS) module.

Enables silent background printing directly to physical or network OS printers
(e.g., thermal receipt printers, Wi-Fi printers) via the OS print spooler.
"""

from __future__ import annotations

import contextlib
import logging
import os
import platform
import shutil
import subprocess
import tempfile

from django.utils import timezone

from apps.pos.models import POSSale
from apps.tenancy.models import Organization

logger = logging.getLogger(__name__)

RECEIPT_WIDTH = 40


def format_text_receipt(*, organization: Organization, sale: POSSale) -> str:
    """Format an 80-column plain-text receipt suitable for any POS/thermal/impact printer."""
    inv = sale.invoice
    w = RECEIPT_WIDTH
    created_str = timezone.localtime(sale.created_at).strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "=" * w,
        organization.name.center(w),
        f"RECEIPT #{sale.receipt_number}".center(w),
        "=" * w,
        f"Date: {created_str}",
        f"Register: {sale.register.code} | Shift: {sale.shift.shift_number}",
        f"Cashier: {sale.shift.cashier.get_full_name() or sale.shift.cashier.email}",
    ]
    if sale.customer:
        lines.append(f"Customer: {sale.customer.name}")
    lines.append("-" * w)
    lines.append(f"{'Item':<26}{'Total':>14}")
    lines.append("-" * w)

    for line in inv.lines.all():
        pname = line.product.name[:25]
        ltotal = f"${line.line_total:.2f}"
        lines.append(f"{pname:<26}{ltotal:>14}")
        disc_text = f" (-{line.discount_percent:.0f}%)" if line.discount_percent > 0 else ""
        lines.append(f"  {line.quantity:g} x ${line.unit_price:.2f}{disc_text}")

    lines.append("-" * w)
    lines.append(f"{'Subtotal:':<26}{f'${inv.subtotal:.2f}':>14}")
    if inv.discount_total > 0:
        lines.append(f"{'Discount:':<26}{f'-${inv.discount_total:.2f}':>14}")
    if inv.tax_total > 0:
        lines.append(f"{'Tax:':<26}{f'${inv.tax_total:.2f}':>14}")
    lines.append(f"{'TOTAL:':<26}{f'${sale.total_amount:.2f}':>14}")
    lines.append("-" * w)
    lines.append("Payment Details:")
    for tender in sale.tenders:
        mname = str(tender.get("payment_method", "Cash")).capitalize()
        amt = tender.get("amount", 0)
        lines.append(f"  {mname:<24}{f'${float(amt):.2f}':>14}")

    if sale.amount_tendered:
        lines.append(f"  {'Amount Received:':<24}{f'${sale.amount_tendered:.2f}':>14}")
        lines.append(f"  {'Change Given:':<24}{f'${sale.change_given:.2f}':>14}")

    lines.append("=" * w)
    footer = sale.register.receipt_footer or "Thank you for your business!"
    for fline in footer.splitlines():
        lines.append(fline.center(w))
    lines.append("=" * w)
    lines.extend(["", "", "", "", ""])  # Feed lines for tear/cutter
    return "\n".join(lines)


def format_test_slip(*, organization: Organization, printer_name: str) -> str:
    """Format a short test slip to confirm printer connectivity."""
    w = RECEIPT_WIDTH
    now_str = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "=" * w,
        organization.name.center(w),
        "PRINTER TEST SLIP".center(w),
        "=" * w,
        f"Time: {now_str}",
        f"Printer: {printer_name}",
        "Status: Online / Ready",
        "-" * w,
        "If you can read this, your hardware",
        "printer is properly connected and ready",
        "to print POS receipts automatically.",
        "=" * w,
        "Powered by Business OS".center(w),
        "=" * w,
        "",
        "",
        "",
        "",
    ]
    return "\n".join(lines)


_WINDOWS_PRINT_SCRIPT = """param([string]$printerName, [string]$filePath)
Add-Type -AssemblyName System.Drawing
$doc = New-Object System.Drawing.Printing.PrintDocument
$doc.PrinterSettings.PrinterName = $printerName
$doc.PrintController = New-Object System.Drawing.Printing.StandardPrintController
$lines = Get-Content -Path $filePath -Encoding utf8
$doc.add_PrintPage({
    param($sender, $e)
    $font = New-Object System.Drawing.Font("Consolas", 9.5, [System.Drawing.FontStyle]::Regular)
    $brush = [System.Drawing.Brushes]::Black
    $y = 15
    $lineHeight = 14
    foreach ($line in $lines) {
        $e.Graphics.DrawString($line, $font, $brush, 15, $y)
        $y += $lineHeight
    }
    $e.HasMorePages = $false
})
$doc.Print()
"""


def _spool_windows(content: str, printer_name: str) -> bool:
    """Send text stream directly to Windows printer via .NET StandardPrintController."""
    ps_path = ""
    txt_path = ""
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".ps1") as pf:
            pf.write(_WINDOWS_PRINT_SCRIPT)
            ps_path = pf.name

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".txt") as tf:
            tf.write(content)
            txt_path = tf.name

        cmd = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            ps_path,
            printer_name,
            txt_path,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)  # noqa: S603
        if res.returncode != 0:
            logger.warning("Windows printer spooling failed (%d): %s", res.returncode, res.stderr)
            return False
        return True
    except Exception as exc:
        logger.warning("Failed to spool print job on Windows to '%s': %s", printer_name, exc)
        return False
    finally:
        for path in (ps_path, txt_path):
            if path and os.path.exists(path):
                with contextlib.suppress(Exception):
                    os.remove(path)


def _spool_unix(content: str, printer_name: str) -> bool:
    """Send text stream directly to Unix/CUPS printer via lp or lpr."""
    lp = shutil.which("lp") or shutil.which("lpr")
    if not lp:
        logger.debug("No Unix lp or lpr utility found in PATH.")
        return False

    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".txt") as tf:
            tf.write(content)
            temp_path = tf.name

        flag = "-d" if "lp" in lp else "-P"
        res = subprocess.run([lp, flag, printer_name, temp_path], capture_output=True, timeout=10, check=False)  # noqa: S603
        return res.returncode == 0
    except Exception as exc:
        logger.warning("Failed to spool print job on Unix to '%s': %s", printer_name, exc)
        return False
    finally:
        if temp_path and os.path.exists(temp_path):
            with contextlib.suppress(Exception):
                os.remove(temp_path)


def spool_receipt_to_printer(*, organization: Organization, sale: POSSale, printer_name: str) -> bool:
    """Spool a sale receipt directly to an installed physical/network OS printer."""
    if not printer_name:
        return False
    slip = format_text_receipt(organization=organization, sale=sale)
    sys_name = platform.system()
    if sys_name == "Windows":
        return _spool_windows(slip, printer_name)
    if sys_name in ("Linux", "Darwin"):
        return _spool_unix(slip, printer_name)
    return False


def spool_test_slip_to_printer(*, organization: Organization, printer_name: str) -> bool:
    """Spool a test slip directly to an installed physical/network OS printer."""
    if not printer_name:
        return False
    slip = format_test_slip(organization=organization, printer_name=printer_name)
    sys_name = platform.system()
    if sys_name == "Windows":
        return _spool_windows(slip, printer_name)
    if sys_name in ("Linux", "Darwin"):
        return _spool_unix(slip, printer_name)
    return False
