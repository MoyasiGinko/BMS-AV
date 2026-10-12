"""ReportLab PDF generator for employee payslips."""

from __future__ import annotations

import io
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.payroll.models import Payslip, SalaryComponentType


def _build_styles() -> dict[str, ParagraphStyle]:
    """Build typography and styling rules for payslip PDF."""
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "DocTitle",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=colors.HexColor("#1e293b"),
        ),
        "subtitle": ParagraphStyle(
            "DocSubtitle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#64748b"),
        ),
        "section": ParagraphStyle(
            "SectionTitle",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=16,
            textColor=colors.HexColor("#0f172a"),
        ),
        "cell_label": ParagraphStyle(
            "CellLabel",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#475569"),
        ),
        "cell_value": ParagraphStyle(
            "CellValue",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#0f172a"),
        ),
        "money": ParagraphStyle(
            "MoneyBold",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=13,
            alignment=2,
            textColor=colors.HexColor("#0f172a"),
        ),
        "net_pay": ParagraphStyle(
            "NetPayStyle",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=20,
            alignment=2,
            textColor=colors.HexColor("#0284c7"),
        ),
    }


def _build_header_table(payslip: Payslip, styles: dict[str, ParagraphStyle]) -> Table:
    """Build header section showing company, pay period, and run number."""
    run = payslip.payroll_run
    p_start = run.period_start.strftime("%b %d, %Y")
    p_end = run.period_end.strftime("%b %d, %Y")
    pay_date = run.payment_date.strftime("%b %d, %Y")

    table = Table(
        [
            [
                Paragraph(payslip.organization.name, styles["title"]),
                Paragraph(f"PAYSLIP #{run.number}", styles["title"]),
            ],
            [
                Paragraph(f"Pay Period: {p_start} — {p_end}", styles["subtitle"]),
                Paragraph(f"Payment Date: {pay_date}", styles["subtitle"]),
            ],
        ],
        colWidths=[300, 240],
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return table


def _build_info_table(payslip: Payslip, styles: dict[str, ParagraphStyle]) -> Table:
    """Build employee and payment detail grid."""
    emp = payslip.employee
    dept = emp.department.name if emp.department else "—"
    pos = emp.position.title if emp.position else "—"
    bank = f"{payslip.bank_name} ({payslip.bank_account_number})" if payslip.bank_name else "—"

    data = [
        [
            Paragraph("Employee Name:", styles["cell_label"]),
            Paragraph(emp.full_name, styles["cell_value"]),
            Paragraph("Department:", styles["cell_label"]),
            Paragraph(dept, styles["cell_value"]),
        ],
        [
            Paragraph("Employee Code:", styles["cell_label"]),
            Paragraph(emp.code, styles["cell_value"]),
            Paragraph("Position:", styles["cell_label"]),
            Paragraph(pos, styles["cell_value"]),
        ],
        [
            Paragraph("Payment Method:", styles["cell_label"]),
            Paragraph(payslip.get_payment_method_display(), styles["cell_value"]),
            Paragraph("Working Days:", styles["cell_label"]),
            Paragraph(str(payslip.working_days), styles["cell_value"]),
        ],
        [
            Paragraph("Bank Account:", styles["cell_label"]),
            Paragraph(bank, styles["cell_value"]),
            Paragraph("Unpaid Leave Days:", styles["cell_label"]),
            Paragraph(str(payslip.unpaid_leave_days), styles["cell_value"]),
        ],
    ]
    table = Table(data, colWidths=[100, 170, 110, 160])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#f1f5f9")),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def _build_breakdown_table(payslip: Payslip, styles: dict[str, ParagraphStyle]) -> Table:
    """Build side-by-side earnings and deductions table with totals."""
    earnings = [item for item in payslip.items.all() if item.component_type == SalaryComponentType.EARNING]
    deductions = [
        item for item in payslip.items.all() if item.component_type == SalaryComponentType.DEDUCTION
    ]

    data: list[list[Any]] = [
        [
            Paragraph("<b>EARNINGS</b>", styles["section"]),
            Paragraph("<b>AMOUNT</b>", styles["money"]),
            Paragraph("<b>DEDUCTIONS</b>", styles["section"]),
            Paragraph("<b>AMOUNT</b>", styles["money"]),
        ]
    ]

    max_rows = max(len(earnings), len(deductions), 1)
    for i in range(max_rows):
        e_name = earnings[i].name if i < len(earnings) else ""
        e_amt = f"{earnings[i].amount:,.2f}" if i < len(earnings) else ""
        d_name = deductions[i].name if i < len(deductions) else ""
        d_amt = f"{deductions[i].amount:,.2f}" if i < len(deductions) else ""
        data.append(
            [
                Paragraph(e_name, styles["cell_value"]),
                Paragraph(e_amt, styles["money"]),
                Paragraph(d_name, styles["cell_value"]),
                Paragraph(d_amt, styles["money"]),
            ]
        )

    data.append(
        [
            Paragraph("<b>Total Gross Earnings</b>", styles["cell_label"]),
            Paragraph(f"<b>{payslip.gross_pay:,.2f}</b>", styles["money"]),
            Paragraph("<b>Total Deductions</b>", styles["cell_label"]),
            Paragraph(f"<b>{payslip.total_deductions:,.2f}</b>", styles["money"]),
        ]
    )

    table = Table(data, colWidths=[180, 90, 180, 90])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#cbd5e1")),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f8fafc")),
                ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#cbd5e1")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#f1f5f9")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def _build_net_box(payslip: Payslip, styles: dict[str, ParagraphStyle]) -> Table:
    """Build highlight callout box for net pay."""
    currency_code = getattr(payslip.organization, "base_currency", "USD") or "USD"
    data = [
        [
            Paragraph("<b>NET TAKE-HOME PAY</b>", styles["section"]),
            Paragraph(f"{currency_code} {payslip.net_pay:,.2f}", styles["net_pay"]),
        ]
    ]
    table = Table(data, colWidths=[270, 270])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#e0f2fe")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#0284c7")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ]
        )
    )
    return table


def generate_payslip_pdf(*, payslip: Payslip) -> bytes:
    """Generate a clean, professional PDF document for an employee payslip."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )
    styles = _build_styles()
    story = [
        _build_header_table(payslip, styles),
        Spacer(1, 12),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#cbd5e1")),
        Spacer(1, 14),
        _build_info_table(payslip, styles),
        Spacer(1, 18),
        _build_breakdown_table(payslip, styles),
        Spacer(1, 16),
        _build_net_box(payslip, styles),
        Spacer(1, 30),
        Paragraph(
            "CONFIDENTIAL: This payslip contains proprietary and confidential information. "
            "Generated electronically by Business OS ERP. No signature required.",
            styles["subtitle"],
        ),
    ]

    doc.build(story)
    return buffer.getvalue()
