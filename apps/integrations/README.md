# Integrations & Import/Export Module

## Purpose
The `apps.integrations` module provides an enterprise-grade data onboarding and transfer framework:
1. **Validate-Preview-Commit Imports**: Safe, multi-step bulk data import for products catalog, customer directory, and future entities (CSV and XLSX).
   - **Upload & Validate**: Parses input files, normalizes headers, validates schemas, types, and constraints without touching the database.
   - **Preview & Inspect**: Interactive UI showing summary metrics, valid rows sample, and detailed row-level error reports.
   - **Commit**: Transactional commit into domain services (`apps.catalog.services`, `apps.customers.services`), tracking created/updated/skipped counts and publishing domain events.
2. **Entity Data Exports**: Background generation of CSV (RFC 4180 with utf-8-sig BOM) and XLSX (`openpyxl`) files for operational datasets.
3. **Template Engine**: Dynamic generation of official CSV and XLSX templates pre-populated with column headers and sample data.

## Models
- `ImportJob(TenantModel)`: Tracks import lifecycle (`uploaded` -> `validating` -> `validated` -> `committing` -> `completed` / `failed`), stores uploaded file, options, preview rows, and row validation errors.
- `ExportJob(TenantModel)`: Tracks background entity dataset exports and completed file artifacts.

Both models enforce PostgreSQL Row-Level Security (RLS) policies.

## Architecture
- Layered in the top application tier (`apps.reports | apps.ai_assistant | apps.automation | apps.integrations`).
- Depends downward on `catalog`, `customers`, and `core`.
- Pluggable importer architecture via `BaseEntityImporter` and registry.
- Pluggable exporter architecture via `BaseEntityExporter` and registry.
