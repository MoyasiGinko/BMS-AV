"""Base class and format utilities for entity data exporters."""

from __future__ import annotations

import csv
import io
from abc import ABC, abstractmethod
from typing import Any

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from apps.tenancy.models import Organization


class BaseEntityExporter(ABC):
    """Abstract entity data exporter supporting streaming CSV and styled XLSX."""

    entity_type: str = ""
    display_name: str = ""

    @abstractmethod
    def export(
        self,
        organization: Organization,
        file_format: str,
        filters: dict[str, Any] | None = None,
    ) -> tuple[str, bytes, int]:
        """Export dataset returning (filename, bytes_content, row_count)."""
        ...

    def build_csv(self, filename: str, headers: list[str], rows: list[list[Any]]) -> tuple[str, bytes, int]:
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(headers)
        for r in rows:
            writer.writerow(r)
        content = stream.getvalue().encode("utf-8-sig")
        return filename, content, len(rows)

    def build_xlsx(
        self,
        filename: str,
        sheet_title: str,
        headers: list[str],
        rows: list[list[Any]],
    ) -> tuple[str, bytes, int]:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = sheet_title[:31]

        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="334155", end_color="334155", fill_type="solid")
        header_align = Alignment(horizontal="center", vertical="center")

        ws.append(headers)
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align

        for r in rows:
            ws.append(r)

        # Autowidth
        for col_idx, col_name in enumerate(headers, start=1):
            col_letter = get_column_letter(col_idx)
            max_len = max(len(str(col_name)), 10)
            for row_idx in range(2, min(len(rows) + 2, 100)):
                cell_val = str(ws.cell(row=row_idx, column=col_idx).value or "")
                max_len = max(max_len, min(len(cell_val), 50))
            ws.column_dimensions[col_letter].width = max_len + 3

        stream = io.BytesIO()
        wb.save(stream)
        return filename, stream.getvalue(), len(rows)
