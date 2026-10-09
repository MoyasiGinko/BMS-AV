"""Base abstractions and data structures for entity importers."""

from __future__ import annotations

import csv
import io
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import openpyxl
from django.utils.translation import gettext as _

from apps.tenancy.models import Organization


@dataclass(frozen=True)
class RowError:
    row_number: int
    field: str
    message: str
    raw_data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationResult:
    total_rows: int
    valid_rows: int
    error_rows: int
    errors: list[RowError]
    preview_rows: list[dict[str, Any]]
    parsed_rows: list[dict[str, Any]]

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "total_rows": self.total_rows,
            "valid_rows": self.valid_rows,
            "error_rows": self.error_rows,
            "errors": [e.to_dict() for e in self.errors],
            "preview_rows": self.preview_rows,
        }


@dataclass(frozen=True)
class CommitResult:
    created_count: int
    updated_count: int
    skipped_count: int
    errors: list[str]


class BaseEntityImporter(ABC):
    """Abstract entity importer defining validate-preview-commit lifecycle."""

    entity_type: str = ""
    display_name: str = ""

    def parse_file(self, file_content: bytes, file_format: str) -> list[dict[str, Any]]:
        """Parse raw file bytes into a list of normalized row dictionaries."""
        if file_format.lower() == "xlsx":
            return self._parse_xlsx(file_content)
        return self._parse_csv(file_content)

    def _parse_csv(self, file_content: bytes) -> list[dict[str, Any]]:
        encodings = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]
        text_content = ""
        for enc in encodings:
            try:
                text_content = file_content.decode(enc)
                break
            except UnicodeDecodeError:
                continue

        if not text_content:
            raise ValueError(_("Could not decode CSV file with supported encodings (UTF-8, Latin-1)."))

        stream = io.StringIO(text_content)
        reader = csv.reader(stream)
        try:
            raw_headers = next(reader)
        except StopIteration:
            return []

        # Normalize headers: lower case, stripped, replace spaces/dashes with underscores
        headers = [
            h.strip().lstrip("\ufeff").lower().replace(" ", "_").replace("-", "_") for h in raw_headers
        ]

        rows: list[dict[str, Any]] = []
        for row_vals in reader:
            if not row_vals or not any(str(v).strip() for v in row_vals):
                continue
            row_dict: dict[str, Any] = {}
            for idx, val in enumerate(row_vals):
                if idx < len(headers):
                    key = headers[idx]
                    if key:
                        row_dict[key] = str(val).strip()
            rows.append(row_dict)
        return rows

    def _parse_xlsx(self, file_content: bytes) -> list[dict[str, Any]]:
        wb = openpyxl.load_workbook(io.BytesIO(file_content), data_only=True)
        sheet = wb.active
        if sheet is None:
            return []

        rows_iter = sheet.iter_rows(values_only=True)
        try:
            raw_headers = next(rows_iter)
        except StopIteration:
            return []

        headers = [
            str(h).strip().lower().replace(" ", "_").replace("-", "_")
            for h in raw_headers
            if h is not None and str(h).strip()
        ]

        rows: list[dict[str, Any]] = []
        for raw_row in rows_iter:
            if not raw_row or not any(v is not None and str(v).strip() for v in raw_row):
                continue
            row_dict: dict[str, Any] = {}
            for idx, val in enumerate(raw_row):
                if idx < len(headers):
                    key = headers[idx]
                    if key:
                        row_dict[key] = "" if val is None else str(val).strip()
            rows.append(row_dict)
        return rows

    @staticmethod
    def parse_decimal(val: Any, default: Decimal = Decimal("0.0000")) -> Decimal:
        if val is None or str(val).strip() == "":
            return default
        clean_str = str(val).replace("$", "").replace(",", "").strip()
        try:
            return Decimal(clean_str).quantize(Decimal("0.0001"))
        except InvalidOperation, ValueError:
            raise ValueError(f"Invalid decimal value: '{val}'") from None

    @staticmethod
    def parse_bool(val: Any, default: bool = True) -> bool:
        if val is None or str(val).strip() == "":
            return default
        s = str(val).strip().lower()
        if s in ("true", "1", "yes", "y", "active", "enabled"):
            return True
        if s in ("false", "0", "no", "n", "inactive", "disabled"):
            return False
        return default

    @abstractmethod
    def validate_batch(
        self,
        organization: Organization,
        rows: list[dict[str, Any]],
        options: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """Inspect and validate parsed rows without performing database writes."""
        ...

    @abstractmethod
    def commit_batch(
        self,
        organization: Organization,
        rows: list[dict[str, Any]],
        options: dict[str, Any] | None = None,
        actor: Any = None,
    ) -> CommitResult:
        """Atomically commit valid rows to the database using domain services."""
        ...

    @abstractmethod
    def generate_template(self, file_format: str) -> tuple[str, bytes]:
        """Generate a sample template file (CSV or XLSX) with column headers and sample data."""
        ...
