"""Product catalog entity importer with validate-preview-commit lifecycle."""

from __future__ import annotations

import csv
import io
from decimal import Decimal
from typing import Any

import openpyxl
from django.db import transaction
from django.utils.text import slugify

from apps.catalog import services as catalog_services
from apps.catalog.models import Category, Product, ProductType, Unit
from apps.integrations.importers.base import BaseEntityImporter, CommitResult, RowError, ValidationResult
from apps.tenancy.models import Organization

DEFAULT_DECIMAL = Decimal("0.0000")


class ProductImporter(BaseEntityImporter):
    entity_type = "products"
    display_name = "Products Catalog"

    def _resolve_category(
        self,
        organization: Organization,
        cat_name: str,
        create_missing: bool,
    ) -> Category | None:
        if not cat_name:
            return None
        category_obj = Category.all_tenants.filter(organization=organization, name__iexact=cat_name).first()
        if not category_obj and create_missing:
            slug = slugify(cat_name) or "cat"
            base_slug = slug
            s_idx = 1
            while Category.all_tenants.filter(organization=organization, slug=slug).exists():
                slug = f"{base_slug}-{s_idx}"
                s_idx += 1
            category_obj = Category.objects.create(
                organization=organization,
                name=cat_name,
                slug=slug,
            )
        return category_obj

    def _resolve_unit(
        self,
        organization: Organization,
        unit_name: str,
        create_missing: bool,
        default_unit: Unit,
    ) -> Unit:
        if not unit_name:
            return default_unit
        unit_obj = Unit.all_tenants.filter(organization=organization, code__iexact=unit_name).first()
        if not unit_obj:
            unit_obj = Unit.all_tenants.filter(organization=organization, name__iexact=unit_name).first()
        if not unit_obj and create_missing:
            code = unit_name.lower().replace(" ", "")[:10]
            if not Unit.all_tenants.filter(organization=organization, code=code).exists():
                unit_obj = Unit.objects.create(
                    organization=organization,
                    name=unit_name,
                    code=code,
                    precision=0,
                )
        return unit_obj or default_unit

    def _validate_row(
        self,
        idx: int,
        row: dict[str, Any],
        *,
        seen_skus: dict[str, int],
        existing_skus_lower: dict[str, str],
        existing_categories: dict[str, Category],
        existing_units: dict[str, Unit],
        update_existing: bool,
        create_missing: bool,
    ) -> tuple[dict[str, Any], list[RowError]]:
        errors: list[RowError] = []
        sku = str(row.get("sku", "")).strip()
        name = str(row.get("name", "")).strip()

        if not sku:
            errors.append(RowError(row_number=idx, field="sku", message="SKU is required.", raw_data=row))
        if not name:
            errors.append(
                RowError(row_number=idx, field="name", message="Product name is required.", raw_data=row)
            )

        sku_lower = sku.lower()
        if sku:
            if sku_lower in seen_skus:
                msg = (
                    f"Duplicate SKU '{sku}' found in upload file (first seen at row {seen_skus[sku_lower]})."
                )
                errors.append(RowError(row_number=idx, field="sku", message=msg, raw_data=row))
            else:
                seen_skus[sku_lower] = idx

        is_existing = sku_lower in existing_skus_lower
        if is_existing and not update_existing:
            msg = f"SKU '{sku}' already exists in database and 'update_existing' is disabled."
            errors.append(RowError(row_number=idx, field="sku", message=msg, raw_data=row))

        cost_price = DEFAULT_DECIMAL
        try:
            cost_price = self.parse_decimal(row.get("cost_price", "0"))
            if cost_price < Decimal("0"):
                errors.append(
                    RowError(
                        row_number=idx,
                        field="cost_price",
                        message="Cost price must be non-negative.",
                        raw_data=row,
                    )
                )
        except Exception as e:
            errors.append(RowError(row_number=idx, field="cost_price", message=str(e), raw_data=row))

        selling_price = DEFAULT_DECIMAL
        try:
            selling_price = self.parse_decimal(row.get("selling_price", "0"))
            if selling_price < Decimal("0"):
                errors.append(
                    RowError(
                        row_number=idx,
                        field="selling_price",
                        message="Selling price must be non-negative.",
                        raw_data=row,
                    )
                )
        except Exception as e:
            errors.append(RowError(row_number=idx, field="selling_price", message=str(e), raw_data=row))

        raw_type = str(row.get("type", ProductType.STOCK)).strip().lower()
        product_type = raw_type if raw_type in {t.value for t in ProductType} else ProductType.STOCK

        raw_cat = str(row.get("category", "")).strip()
        if raw_cat and raw_cat.lower() not in existing_categories and not create_missing:
            msg = f"Category '{raw_cat}' does not exist and auto-creation is disabled."
            errors.append(RowError(row_number=idx, field="category", message=msg, raw_data=row))

        raw_unit = str(row.get("unit", "")).strip()
        if raw_unit and raw_unit.lower() not in existing_units and not create_missing:
            msg = f"Unit '{raw_unit}' does not exist and auto-creation is disabled."
            errors.append(RowError(row_number=idx, field="unit", message=msg, raw_data=row))

        clean_row = {
            "row_number": idx,
            "sku": sku,
            "name": name,
            "type": product_type,
            "category": raw_cat,
            "unit": raw_unit,
            "cost_price": cost_price,
            "selling_price": selling_price,
            "barcode": str(row.get("barcode", "")).strip(),
            "description": str(row.get("description", "")).strip(),
            "is_active": self.parse_bool(row.get("is_active", True)),
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
        create_missing = options.get("create_missing", True)

        errors: list[RowError] = []
        preview_rows: list[dict[str, Any]] = []
        parsed_rows: list[dict[str, Any]] = []
        seen_skus: dict[str, int] = {}

        existing_skus = set(
            Product.all_tenants.filter(organization=organization).values_list("sku", flat=True)
        )
        existing_skus_lower = {s.lower(): s for s in existing_skus}

        existing_categories = {
            c.name.lower(): c for c in Category.all_tenants.filter(organization=organization)
        }
        existing_units = {u.code.lower(): u for u in Unit.all_tenants.filter(organization=organization)}
        for u in Unit.all_tenants.filter(organization=organization):
            existing_units[u.name.lower()] = u

        for idx, row in enumerate(rows, start=2):
            clean_row, row_errs = self._validate_row(
                idx=idx,
                row=row,
                seen_skus=seen_skus,
                existing_skus_lower=existing_skus_lower,
                existing_categories=existing_categories,
                existing_units=existing_units,
                update_existing=update_existing,
                create_missing=create_missing,
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
        *,
        update_existing: bool,
        create_missing: bool,
        default_unit: Unit,
        actor: Any,
    ) -> str:
        sku = row["sku"]
        name = row["name"]
        cost_price = row.get("cost_price", DEFAULT_DECIMAL)
        selling_price = row.get("selling_price", DEFAULT_DECIMAL)
        barcode = row.get("barcode", "")
        prod_type = row.get("type", ProductType.STOCK)
        description = row.get("description", "")
        is_active = row.get("is_active", True)

        category_obj = self._resolve_category(organization, row.get("category", ""), create_missing)
        unit_obj = self._resolve_unit(organization, row.get("unit", ""), create_missing, default_unit)

        existing_product = Product.all_tenants.filter(organization=organization, sku__iexact=sku).first()

        if existing_product:
            if not update_existing:
                return "skipped"
            existing_product.name = name
            existing_product.cost_price = cost_price
            existing_product.selling_price = selling_price
            if barcode:
                existing_product.barcode = barcode
            if category_obj:
                existing_product.category = category_obj
            if unit_obj:
                existing_product.unit = unit_obj
            existing_product.description = description
            existing_product.is_active = is_active
            existing_product.save()
            return "updated"

        catalog_services.create_product(
            organization=organization,
            sku=sku,
            name=name,
            type=prod_type,
            category=category_obj,
            unit=unit_obj,
            cost_price=cost_price,
            selling_price=selling_price,
            barcode=barcode,
            description=description,
            is_active=is_active,
            actor=actor,
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
        create_missing = options.get("create_missing", True)

        created_count = 0
        updated_count = 0
        skipped_count = 0

        default_unit = Unit.all_tenants.filter(organization=organization).first()
        if not default_unit:
            default_unit = Unit.objects.create(
                organization=organization,
                name="Piece",
                code="pcs",
                precision=0,
            )

        with transaction.atomic():
            for row in rows:
                if not row.get("is_valid", True):
                    skipped_count += 1
                    continue
                outcome = self._commit_row(
                    organization=organization,
                    row=row,
                    update_existing=update_existing,
                    create_missing=create_missing,
                    default_unit=default_unit,
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
            "sku",
            "name",
            "type",
            "category",
            "unit",
            "cost_price",
            "selling_price",
            "barcode",
            "description",
            "is_active",
        ]
        sample_rows = [
            [
                "PROD-001",
                "Ergonomic Office Chair",
                "stock",
                "Furniture",
                "pcs",
                "85.00",
                "150.00",
                "98765432101",
                "High quality mesh office chair with lumbar support",
                "TRUE",
            ],
            [
                "PROD-002",
                "Wireless Mechanical Keyboard",
                "stock",
                "Electronics",
                "pcs",
                "45.00",
                "89.99",
                "98765432102",
                "RGB backlit wireless mechanical keyboard",
                "TRUE",
            ],
            [
                "SERV-001",
                "Standard Desk Assembly Service",
                "service",
                "Services",
                "hr",
                "20.00",
                "50.00",
                "",
                "On-site furniture assembly per hour",
                "TRUE",
            ],
        ]

        if file_format.lower() == "xlsx":
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Products Import Template"
            ws.append(headers)
            for r in sample_rows:
                ws.append(r)
            xlsx_stream = io.BytesIO()
            wb.save(xlsx_stream)
            return "products_import_template.xlsx", xlsx_stream.getvalue()

        # CSV
        csv_stream = io.StringIO()
        writer = csv.writer(csv_stream)
        writer.writerow(headers)
        for r in sample_rows:
            writer.writerow(r)
        return "products_import_template.csv", csv_stream.getvalue().encode("utf-8-sig")
