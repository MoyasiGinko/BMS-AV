# ADR 0016: Unified Import/Export Framework (validate-preview-commit)

## Context
Bulk importing and exporting operational entities (products, customers, and future entities such as vendors or accounts) is critical for onboarding and daily SaaS operations. Previously, catalog had a basic synchronous CSV reader without previewing, error introspection, or XLSX capability, while customers lacked bulk import/export. Users require an enterprise-grade multi-step workflow:
1. **Upload & Validate**: parse CSV/XLSX without saving records, checking data schemas, types, and business constraints.
2. **Preview & Inspect**: visualize valid rows, inspect specific row-level errors with column names and messages, and review options (e.g., updating existing records by unique key vs skipping).
3. **Commit**: atomically or asynchronously write validated records into domain services (`catalog.services`, `customers.services`), track created/updated/skipped counts, and generate outbox domain events.
4. **Export**: generate structured CSV (RFC 4180 with utf-8-sig BOM) and XLSX (`openpyxl`) files for business entities with background task execution.

## Decisions
1. **Module Placement**:
   - Housed in `apps.integrations`.
   - `apps.integrations` sits at the top layer in `pyproject.toml` (`apps.reports | apps.ai_assistant | apps.automation | apps.integrations`), enabling clean downward imports of `apps.catalog`, `apps.customers`, `apps.core`, etc., without violating architecture layering contracts.
2. **Models & Storage**:
   - `ImportJob(TenantModel)`: tracks lifecycle (`uploaded` -> `validating` -> `validated` -> `committing` -> `completed` / `failed`), stores uploaded file in `imports/%Y/%m/`, stores validation errors list and sample preview data in PostgreSQL JSONFields, and tracks summary counts (`total_rows`, `valid_rows`, `error_rows`, `created_count`, `updated_count`, `skipped_count`).
   - `ExportJob(TenantModel)`: tracks entity data export jobs (`pending` -> `processing` -> `completed` / `failed`), stores output in `exports/%Y/%m/`.
   - Both models enforce PostgreSQL Row-Level Security (RLS) policies.
3. **Importers & Exporters Architecture**:
   - `BaseEntityImporter`: abstract lifecycle for file parsing (CSV with automatic encoding detection and XLSX via openpyxl), batch validation with duplicate checking, transactional commit invoking official domain services, and blank sample template generation.
   - `ProductImporter` & `CustomerImporter`: entity-specific validators and commit handlers.
   - `BaseEntityExporter`, `ProductEntityExporter`, `CustomerEntityExporter`: streaming CSV and openpyxl XLSX generators.
4. **UI & HTMX Interaction**:
   - Interactive UI conforming to design system tokens with three-phase validate-preview-commit screens, tabbed error introspection, sample template downloads, and HTMX status polling for background jobs.

## Consequences
- Clean separation between analytical report exports (`apps.reports`) and operational entity import/export (`apps.integrations`).
- High data safety: users see exactly what will be imported or rejected before committing to database writes.
- Scalable design: adding future imports (suppliers, chart of accounts, employees) only requires registering a new `BaseEntityImporter` subclass.
