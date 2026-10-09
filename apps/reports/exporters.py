"""Report exporters for CSV, Excel (XLSX), and PDF formats."""

from __future__ import annotations

import csv
import io
from typing import Any

from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.reports.models import ExportFileFormat, ReportType


def _meta_sales_product(data: dict[str, Any]) -> tuple[str, list[str], list[list[str]], list[str] | None]:
    title = "Sales by Product Report"
    headers = [
        "SKU",
        "Product Name",
        "Category",
        "Unit",
        "Qty Sold",
        "Gross Sales",
        "Tax",
        "Net Sales",
        "Avg Price",
    ]
    rows = [
        [
            str(r["sku"]),
            str(r["name"]),
            str(r["category_name"]),
            str(r["unit_code"]),
            f"{r['quantity_sold']:.2f}",
            f"{r['gross_sales']:.2f}",
            f"{r['tax_total']:.2f}",
            f"{r['net_sales']:.2f}",
            f"{r['avg_price']:.2f}",
        ]
        for r in data.get("rows", [])
    ]
    s = data.get("summary", {})
    totals = [
        "TOTALS",
        "",
        "",
        "",
        f"{s.get('total_quantity', 0):.2f}",
        f"{s.get('total_gross_sales', 0):.2f}",
        f"{s.get('total_tax', 0):.2f}",
        f"{s.get('total_net_sales', 0):.2f}",
        "",
    ]
    return title, headers, rows, totals


def _meta_sales_customer(data: dict[str, Any]) -> tuple[str, list[str], list[list[str]], list[str] | None]:
    title = "Sales by Customer Report"
    headers = [
        "Customer Code",
        "Customer Name",
        "Invoices",
        "Gross Sales",
        "Tax",
        "Paid",
        "Balance Due",
    ]
    rows = [
        [
            str(r["code"]),
            str(r["name"]),
            str(r["invoice_count"]),
            f"{r['gross_sales']:.2f}",
            f"{r['tax_total']:.2f}",
            f"{r['paid_amount']:.2f}",
            f"{r['balance_due']:.2f}",
        ]
        for r in data.get("rows", [])
    ]
    s = data.get("summary", {})
    totals = [
        "TOTALS",
        "",
        str(s.get("total_invoices", 0)),
        f"{s.get('total_gross_sales', 0):.2f}",
        f"{s.get('total_tax', 0):.2f}",
        f"{s.get('total_paid', 0):.2f}",
        f"{s.get('total_balance_due', 0):.2f}",
    ]
    return title, headers, rows, totals


def _meta_sales_branch(data: dict[str, Any]) -> tuple[str, list[str], list[list[str]], list[str] | None]:
    title = "Sales by Branch Report"
    headers = [
        "Branch Code",
        "Branch Name",
        "Invoices",
        "Direct Sales",
        "POS Sales",
        "Total Sales",
        "Tax",
        "Net Sales",
    ]
    rows = [
        [
            str(r["code"]),
            str(r["name"]),
            str(r["invoice_count"]),
            f"{r['direct_sales']:.2f}",
            f"{r['pos_sales']:.2f}",
            f"{r['gross_sales']:.2f}",
            f"{r['tax_total']:.2f}",
            f"{r['net_sales']:.2f}",
        ]
        for r in data.get("rows", [])
    ]
    s = data.get("summary", {})
    totals = [
        "TOTALS",
        "",
        str(s.get("total_invoices", 0)),
        f"{s.get('total_direct_sales', 0):.2f}",
        f"{s.get('total_pos_sales', 0):.2f}",
        f"{s.get('total_gross_sales', 0):.2f}",
        f"{s.get('total_tax', 0):.2f}",
        f"{s.get('total_net_sales', 0):.2f}",
    ]
    return title, headers, rows, totals


def _meta_sales_day(data: dict[str, Any]) -> tuple[str, list[str], list[list[str]], list[str] | None]:
    title = "Daily Sales Trend Report"
    headers = [
        "Date",
        "Invoices",
        "Direct Sales",
        "POS Sales",
        "Gross Sales",
        "Tax",
        "Net Sales",
    ]
    rows = [
        [
            str(r["date"]),
            str(r["invoice_count"]),
            f"{r['direct_sales']:.2f}",
            f"{r['pos_sales']:.2f}",
            f"{r['gross_sales']:.2f}",
            f"{r['tax_total']:.2f}",
            f"{r['net_sales']:.2f}",
        ]
        for r in data.get("rows", [])
    ]
    s = data.get("summary", {})
    totals = [
        "TOTALS",
        str(s.get("total_invoices", 0)),
        f"{s.get('total_direct_sales', 0):.2f}",
        f"{s.get('total_pos_sales', 0):.2f}",
        f"{s.get('total_gross_sales', 0):.2f}",
        f"{s.get('total_tax', 0):.2f}",
        f"{s.get('total_net_sales', 0):.2f}",
    ]
    return title, headers, rows, totals


def _meta_stock_valuation(data: dict[str, Any]) -> tuple[str, list[str], list[list[str]], list[str] | None]:
    title = "Inventory Stock Valuation Report"
    headers = [
        "SKU",
        "Product Name",
        "Category",
        "Warehouse",
        "On Hand",
        "Reserved",
        "Available",
        "Unit Cost",
        "Total Value",
        "Low Stock",
    ]
    rows = [
        [
            str(r["sku"]),
            str(r["name"]),
            str(r["category_name"]),
            str(r["warehouse_name"]),
            f"{r['on_hand']:.2f}",
            f"{r['reserved']:.2f}",
            f"{r['available']:.2f}",
            f"{r['unit_cost']:.2f}",
            f"{r['valuation']:.2f}",
            "YES" if r["is_low_stock"] else "NO",
        ]
        for r in data.get("rows", [])
    ]
    s = data.get("summary", {})
    totals = [
        "TOTALS",
        "",
        "",
        "",
        f"{s.get('total_on_hand', 0):.2f}",
        f"{s.get('total_reserved', 0):.2f}",
        f"{s.get('total_available', 0):.2f}",
        "",
        f"{s.get('total_valuation', 0):.2f}",
        f"{s.get('low_stock_count', 0)} items",
    ]
    return title, headers, rows, totals


def _meta_stock_movement(data: dict[str, Any]) -> tuple[str, list[str], list[list[str]], list[str] | None]:
    title = "Stock Movement Ledger Report"
    headers = [
        "Date & Time",
        "Type",
        "Reference",
        "Warehouse",
        "SKU",
        "Product Name",
        "Quantity",
        "Unit Cost",
        "Total Cost",
        "Operator",
    ]
    rows = [
        [
            r["occurred_at"].strftime("%Y-%m-%d %H:%M")
            if hasattr(r["occurred_at"], "strftime")
            else str(r["occurred_at"]),
            str(r["movement_type_display"]),
            str(r["reference_id"]),
            str(r["warehouse_name"]),
            str(r["product_sku"]),
            str(r["product_name"]),
            f"{r['quantity']:.2f}",
            f"{r['unit_cost']:.2f}",
            f"{r['total_cost']:.2f}",
            str(r["actor_name"]),
        ]
        for r in data.get("rows", [])
    ]
    s = data.get("summary", {})
    totals = [
        "TOTALS",
        f"Net: {s.get('net_qty', 0):.2f}",
        f"In: {s.get('total_inflow_qty', 0):.2f} / Out: {s.get('total_outflow_qty', 0):.2f}",
        "",
        "",
        "",
        f"{s.get('net_qty', 0):.2f}",
        "",
        f"{s.get('total_inflow_cost', 0):.2f}",
        "",
    ]
    return title, headers, rows, totals


def _meta_customer_statement(
    data: dict[str, Any],
) -> tuple[str, list[str], list[list[str]], list[str] | None]:
    cust = data.get("customer", {})
    title = f"Customer Statement: {cust.get('name', '')} ({cust.get('code', '')})"
    headers = [
        "Date",
        "Transaction",
        "Reference",
        "Description",
        "Debit",
        "Credit",
        "Balance",
    ]
    rows = [
        [
            line["occurred_at"].strftime("%Y-%m-%d")
            if hasattr(line["occurred_at"], "strftime")
            else str(line["occurred_at"]),
            str(line["entry_type_display"]),
            str(line["reference_number"]),
            str(line["description"]),
            f"{line['debit']:.2f}" if line["debit"] else "-",
            f"{line['credit']:.2f}" if line["credit"] else "-",
            f"{line['running_balance']:.2f}",
        ]
        for line in data.get("lines", [])
    ]
    s = data.get("summary", {})
    totals = [
        "CLOSING BALANCE",
        "",
        "",
        "",
        f"{s.get('total_debits', 0):.2f}",
        f"{s.get('total_credits', 0):.2f}",
        f"{data.get('closing_balance', 0):.2f}",
    ]
    return title, headers, rows, totals


META_BUILDERS: dict[str, Any] = {
    ReportType.SALES_BY_PRODUCT: _meta_sales_product,
    ReportType.SALES_BY_CUSTOMER: _meta_sales_customer,
    ReportType.SALES_BY_BRANCH: _meta_sales_branch,
    ReportType.SALES_BY_DAY: _meta_sales_day,
    ReportType.STOCK_VALUATION: _meta_stock_valuation,
    ReportType.STOCK_MOVEMENT: _meta_stock_movement,
    ReportType.CUSTOMER_STATEMENT: _meta_customer_statement,
}


def get_report_meta(
    report_type: str, data: dict[str, Any]
) -> tuple[str, list[str], list[list[str]], list[str] | None]:
    """Extract report title, table headers, string data rows, and optional totals row."""
    builder = META_BUILDERS.get(report_type)
    if builder:
        return builder(data)
    return "Operational Report", ["Item"], [["Data"]], None


def export_to_csv(report_type: str, data: dict[str, Any]) -> tuple[str, bytes]:
    """Generate RFC 4180 compliant CSV bytes."""
    title, headers, rows, totals = get_report_meta(report_type, data)
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{report_type}_{timestamp}.csv"

    buffer = io.StringIO()
    writer = csv.writer(buffer)

    # Header metadata
    writer.writerow([title])
    writer.writerow(["Generated At", timezone.now().strftime("%Y-%m-%d %H:%M:%S UTC")])
    writer.writerow([])

    # Table columns
    writer.writerow(headers)

    # Data rows
    for row in rows:
        writer.writerow(row)

    # Summary row
    if totals:
        writer.writerow([])
        writer.writerow(totals)

    return filename, buffer.getvalue().encode("utf-8-sig")


def export_to_xlsx(report_type: str, data: dict[str, Any], organization_name: str = "") -> tuple[str, bytes]:
    """Generate styled Excel workbook bytes with formatted numbers and auto column width."""
    title, headers, rows, totals = get_report_meta(report_type, data)
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{report_type}_{timestamp}.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]  # Excel sheet title max 31 chars

    # Palette
    title_font = Font(name="Segoe UI", size=15, bold=True, color="0F172A")
    subtitle_font = Font(name="Segoe UI", size=10, italic=True, color="64748B")
    header_font = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    data_font = Font(name="Segoe UI", size=10, color="1E293B")
    zebra_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    totals_font = Font(name="Segoe UI", size=10, bold=True, color="0F172A")

    thin_border = Border(
        left=Side(style="thin", color="E2E8F0"),
        right=Side(style="thin", color="E2E8F0"),
        top=Side(style="thin", color="E2E8F0"),
        bottom=Side(style="thin", color="E2E8F0"),
    )
    totals_border = Border(
        top=Side(style="thin", color="0F172A"),
        bottom=Side(style="double", color="0F172A"),
    )

    # Report Title block
    ws.append([f"{organization_name + ' - ' if organization_name else ''}{title}"])
    ws.cell(row=1, column=1).font = title_font

    ws.append([f"Generated: {timezone.now().strftime('%Y-%m-%d %H:%M:%S UTC')}"])
    ws.cell(row=2, column=1).font = subtitle_font
    ws.append([])  # Blank spacer row

    # Headers
    ws.append(headers)
    header_row_idx = 4
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=header_row_idx, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # Data Rows
    current_row = header_row_idx + 1
    for r_idx, row_values in enumerate(rows):
        ws.append(row_values)
        is_even = r_idx % 2 == 1
        for col_idx in range(1, len(row_values) + 1):
            cell = ws.cell(row=current_row, column=col_idx)
            cell.font = data_font
            cell.border = thin_border
            if is_even:
                cell.fill = zebra_fill
        current_row += 1

    # Totals Row
    if totals:
        ws.append(totals)
        for col_idx in range(1, len(totals) + 1):
            cell = ws.cell(row=current_row, column=col_idx)
            cell.font = totals_font
            cell.border = totals_border

    # Auto-adjust column widths
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            val_str = str(cell.value or "")
            if cell.row > 2:  # Don't size by title
                max_len = max(max_len, len(val_str))
        ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    output = io.BytesIO()
    wb.save(output)
    return filename, output.getvalue()


def export_to_pdf(report_type: str, data: dict[str, Any], organization_name: str = "") -> tuple[str, bytes]:
    """Generate clean, paginated PDF report document bytes via ReportLab."""
    title, headers, rows, totals = get_report_meta(report_type, data)
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{report_type}_{timestamp}.pdf"

    buffer = io.BytesIO()
    # Use landscape letter for wide tables (7+ columns)
    pagesize = landscape(letter) if len(headers) >= 7 else letter
    doc = SimpleDocTemplate(
        buffer,
        pagesize=pagesize,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Heading1"],
        fontSize=16,
        leading=20,
        textColor=colors.HexColor("#0F172A"),
    )
    meta_style = ParagraphStyle(
        "ReportMeta",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#64748B"),
    )
    cell_style = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#1E293B"),
    )
    header_style = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        fontName="Helvetica-Bold",
        textColor=colors.white,
    )

    story: list[Any] = []

    # Title & Metadata
    org_display = f"{organization_name} — " if organization_name else ""
    story.append(Paragraph(f"{org_display}{title}", title_style))
    story.append(
        Paragraph(
            f"Generated on {timezone.now().strftime('%Y-%m-%d %H:%M:%S UTC')} | Total Records: {len(rows)}",
            meta_style,
        )
    )
    story.append(Spacer(1, 14))

    # Build Table elements wrapped in Paragraphs for text wrapping
    table_data: list[list[Any]] = []
    header_row = [Paragraph(str(h), header_style) for h in headers]
    table_data.append(header_row)

    for row in rows:
        table_data.append([Paragraph(str(cell), cell_style) for cell in row])

    if totals:
        totals_style = ParagraphStyle(
            "TableTotals",
            parent=styles["Normal"],
            fontSize=8,
            leading=10,
            fontName="Helvetica-Bold",
            textColor=colors.HexColor("#0F172A"),
        )
        table_data.append([Paragraph(str(cell), totals_style) for cell in totals])

    # Table styling
    t_style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E293B")),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, len(rows)), [colors.white, colors.HexColor("#F8FAFC")]),
    ]
    if totals:
        t_style.append(("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F1F5F9")))
        t_style.append(("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#0F172A")))

    report_table = Table(table_data, repeatRows=1)
    report_table.setStyle(TableStyle(t_style))
    story.append(report_table)

    doc.build(story)
    return filename, buffer.getvalue()


def generate_report_export(
    report_type: str,
    file_format: str,
    data: dict[str, Any],
    organization_name: str = "",
) -> tuple[str, bytes, int]:
    """Unified entry point to generate report file bytes.

    Returns (filename, file_bytes, row_count).
    """
    row_count = len(data.get("rows", data.get("lines", [])))

    if file_format == ExportFileFormat.CSV:
        fname, content = export_to_csv(report_type, data)
    elif file_format == ExportFileFormat.XLSX:
        fname, content = export_to_xlsx(report_type, data, organization_name=organization_name)
    elif file_format == ExportFileFormat.PDF:
        fname, content = export_to_pdf(report_type, data, organization_name=organization_name)
    else:
        raise ValueError(f"Unsupported export file format: {file_format}")

    return fname, content, row_count
