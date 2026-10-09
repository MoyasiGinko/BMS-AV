"""Customer accounts entity importer with validate-preview-commit lifecycle."""

from __future__ import annotations

import csv
import io
import re
from decimal import Decimal
from typing import Any

import openpyxl
from django.db import transaction

from apps.customers import services as customer_services
from apps.customers.models import AddressType, Customer
from apps.integrations.importers.base import BaseEntityImporter, CommitResult, RowError, ValidationResult
from apps.tenancy.models import Organization

DEFAULT_DECIMAL = Decimal("0.0000")
EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class CustomerImporter(BaseEntityImporter):
    entity_type = "customers"
    display_name = "Customers"

    def _validate_row(
        self,
        idx: int,
        row: dict[str, Any],
        *,
        seen_codes: dict[str, int],
        existing_codes_lower: dict[str, str],
        update_existing: bool,
        organization: Organization,
    ) -> tuple[dict[str, Any], list[RowError]]:
        errors: list[RowError] = []
        code = str(row.get("code", "")).strip()
        name = str(row.get("name", "")).strip()
        email = str(row.get("email", "")).strip()
        phone = str(row.get("phone", "")).strip()

        if not name:
            errors.append(
                RowError(row_number=idx, field="name", message="Customer name is required.", raw_data=row)
            )

        code_lower = code.lower()
        if code:
            if code_lower in seen_codes:
                msg = (
                    f"Duplicate customer code '{code}' in upload file "
                    f"(first seen at row {seen_codes[code_lower]})."
                )
                errors.append(RowError(row_number=idx, field="code", message=msg, raw_data=row))
            else:
                seen_codes[code_lower] = idx

        is_existing = bool(code and code_lower in existing_codes_lower)
        if is_existing and not update_existing:
            msg = f"Customer code '{code}' already exists and 'update_existing' is disabled."
            errors.append(RowError(row_number=idx, field="code", message=msg, raw_data=row))

        if email and not EMAIL_REGEX.match(email):
            msg = f"Invalid email format: '{email}'"
            errors.append(RowError(row_number=idx, field="email", message=msg, raw_data=row))

        credit_limit = DEFAULT_DECIMAL
        try:
            credit_limit = self.parse_decimal(row.get("credit_limit", "0"))
            if credit_limit < Decimal("0"):
                errors.append(
                    RowError(
                        row_number=idx,
                        field="credit_limit",
                        message="Credit limit must be non-negative.",
                        raw_data=row,
                    )
                )
        except Exception as e:
            errors.append(RowError(row_number=idx, field="credit_limit", message=str(e), raw_data=row))

        terms = 0
        raw_terms = row.get("payment_terms_days", row.get("payment_terms", 0))
        if raw_terms:
            try:
                terms = int(raw_terms)
                if terms < 0:
                    errors.append(
                        RowError(
                            row_number=idx,
                            field="payment_terms_days",
                            message="Payment terms cannot be negative.",
                            raw_data=row,
                        )
                    )
            except Exception as e:
                errors.append(
                    RowError(row_number=idx, field="payment_terms_days", message=str(e), raw_data=row)
                )

        clean_row = {
            "row_number": idx,
            "code": code,
            "name": name,
            "email": email,
            "phone": phone,
            "tax_id": str(row.get("tax_id", "")).strip(),
            "credit_limit": credit_limit,
            "payment_terms_days": terms,
            "currency": str(row.get("currency", organization.base_currency)).strip()
            or organization.base_currency,
            "notes": str(row.get("notes", "")).strip(),
            "address_line1": str(row.get("address_line1", "")).strip(),
            "city": str(row.get("city", "")).strip(),
            "state": str(row.get("state", "")).strip(),
            "postal_code": str(row.get("postal_code", "")).strip(),
            "country": str(row.get("country", "")).strip()[:2].upper(),
            "contact_name": str(row.get("contact_name", "")).strip(),
            "contact_email": str(row.get("contact_email", "")).strip(),
            "contact_phone": str(row.get("contact_phone", "")).strip(),
            "is_update": is_existing,
            "is_valid": len(errors) == 0,
        }
        return clean_row, errors

    def validate_batch(
        self,
        organization: Organization,
        rows: list[dict[str, Any]],
        options: dict[str, Any] | None = None,
    ) -> ValidationResult:
        options = options or {}
        update_existing = options.get("update_existing", True)

        errors: list[RowError] = []
        preview_rows: list[dict[str, Any]] = []
        parsed_rows: list[dict[str, Any]] = []
        seen_codes: dict[str, int] = {}

        existing_codes = set(
            Customer.all_tenants.filter(organization=organization).values_list("code", flat=True)
        )
        existing_codes_lower = {c.lower(): c for c in existing_codes if c}

        for idx, row in enumerate(rows, start=2):
            clean_row, row_errs = self._validate_row(
                idx=idx,
                row=row,
                seen_codes=seen_codes,
                existing_codes_lower=existing_codes_lower,
                update_existing=update_existing,
                organization=organization,
            )
            errors.extend(row_errs)
            parsed_rows.append(clean_row)
            if len(preview_rows) < 20:
                preview_rows.append(clean_row)

        total_rows = len(rows)
        error_rows_count = len({e.row_number for e in errors})
        valid_rows_count = total_rows - error_rows_count

        return ValidationResult(
            total_rows=total_rows,
            valid_rows=valid_rows_count,
            error_rows=error_rows_count,
            errors=errors,
            preview_rows=preview_rows,
            parsed_rows=parsed_rows,
        )

    def _commit_row(
        self,
        organization: Organization,
        row: dict[str, Any],
        update_existing: bool,
        actor: Any,
    ) -> str:
        code = row.get("code")
        name = row["name"]
        email = row.get("email", "")
        phone = row.get("phone", "")
        tax_id = row.get("tax_id", "")
        credit_limit = row.get("credit_limit", DEFAULT_DECIMAL)
        payment_terms_days = row.get("payment_terms_days", 0)
        currency = row.get("currency", organization.base_currency)
        notes = row.get("notes", "")

        existing_customer = None
        if code:
            existing_customer = Customer.all_tenants.filter(
                organization=organization, code__iexact=code
            ).first()

        if existing_customer:
            if not update_existing:
                return "skipped"
            existing_customer.name = name
            if email:
                existing_customer.email = email
            if phone:
                existing_customer.phone = phone
            if tax_id:
                existing_customer.tax_id = tax_id
            existing_customer.credit_limit = credit_limit
            existing_customer.payment_terms_days = payment_terms_days
            if notes:
                existing_customer.notes = notes
            existing_customer.save()
            return "updated"

        cust = customer_services.create_customer(
            organization=organization,
            name=name,
            code=code or None,
            email=email,
            phone=phone,
            tax_id=tax_id,
            credit_limit=credit_limit,
            payment_terms_days=payment_terms_days,
            currency=currency,
            notes=notes,
            actor=actor,
        )

        addr1 = row.get("address_line1")
        if addr1:
            customer_services.add_customer_address(
                organization=organization,
                customer=cust,
                type=AddressType.BILLING,
                line1=addr1,
                city=row.get("city", ""),
                state_or_province=row.get("state", ""),
                postal_code=row.get("postal_code", ""),
                country=row.get("country", "") or "US",
                is_default=True,
            )

        contact_name = row.get("contact_name")
        if contact_name:
            c_parts = str(contact_name).strip().split(" ", 1)
            c_first = c_parts[0]
            c_last = c_parts[1] if len(c_parts) > 1 else ""
            customer_services.add_customer_contact(
                organization=organization,
                customer=cust,
                first_name=c_first,
                last_name=c_last,
                email=row.get("contact_email", ""),
                phone=row.get("contact_phone", ""),
                is_primary=True,
            )

        return "created"

    def commit_batch(
        self,
        organization: Organization,
        rows: list[dict[str, Any]],
        options: dict[str, Any] | None = None,
        actor: Any = None,
    ) -> CommitResult:
        options = options or {}
        update_existing = options.get("update_existing", True)

        created_count = 0
        updated_count = 0
        skipped_count = 0

        with transaction.atomic():
            for row in rows:
                if not row.get("is_valid", True):
                    skipped_count += 1
                    continue
                outcome = self._commit_row(
                    organization=organization,
                    row=row,
                    update_existing=update_existing,
                    actor=actor,
                )
                if outcome == "created":
                    created_count += 1
                elif outcome == "updated":
                    updated_count += 1
                else:
                    skipped_count += 1

        return CommitResult(
            created_count=created_count,
            updated_count=updated_count,
            skipped_count=skipped_count,
            errors=[],
        )

    def generate_template(self, file_format: str) -> tuple[str, bytes]:
        headers = [
            "code",
            "name",
            "email",
            "phone",
            "tax_id",
            "credit_limit",
            "payment_terms_days",
            "currency",
            "address_line1",
            "city",
            "state",
            "postal_code",
            "country",
            "contact_name",
            "contact_email",
            "contact_phone",
            "notes",
        ]
        sample_rows = [
            [
                "CUST-001",
                "Acme Corporation",
                "billing@acme.example.com",
                "+1-555-0199",
                "US-987654321",
                "5000.00",
                "30",
                "USD",
                "123 Corporate Blvd",
                "San Francisco",
                "CA",
                "94105",
                "US",
                "Jane Doe",
                "j.doe@acme.example.com",
                "+1-555-0198",
                "Enterprise partner with net-30 terms",
            ],
            [
                "CUST-002",
                "Global Logistics LLC",
                "ops@globallogistics.example.com",
                "+1-555-0244",
                "US-123456789",
                "10000.00",
                "15",
                "USD",
                "456 Warehouse Way",
                "Chicago",
                "IL",
                "60601",
                "US",
                "John Smith",
                "smith@globallogistics.example.com",
                "+1-555-0245",
                "Primary freight customer",
            ],
        ]

        if file_format.lower() == "xlsx":
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Customers Import Template"
            ws.append(headers)
            for r in sample_rows:
                ws.append(r)
            xlsx_stream = io.BytesIO()
            wb.save(xlsx_stream)
            return "customers_import_template.xlsx", xlsx_stream.getvalue()

        # CSV
        csv_stream = io.StringIO()
        writer = csv.writer(csv_stream)
        writer.writerow(headers)
        for r in sample_rows:
            writer.writerow(r)
        return "customers_import_template.csv", csv_stream.getvalue().encode("utf-8-sig")
