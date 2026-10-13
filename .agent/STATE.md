# Build State (updated by the agent after every task)

- Phase: P5 ERP maturity
- Last completed task: P5-07 Full-tenant export/import (data portability) + retention settings + GDPR-style deletion/export workflows
- Next task: P5-08 Notifications center (in-app + email), user notification preferences
- Open `[!]` tasks: none
- Last `make verify`: PASSED (83/83 integrations tests passing, mypy 34 files clean, ruff check and format clean, lint-imports clean)
- Notes:
  - P5-07 Complete: Data portability (tenant export/import), configurable data retention policies, and GDPR compliance workflows:
    - ADR 0031 (`docs/adr/0031-data-portability-retention-and-gdpr.md`): Full-tenant archive format (ZIP manifest with scoped JSON datasets), transactional schema validation, safe idempotent import, and GDPR erasure with financial immutable ledger preservation.
    - Data Models: `TenantExportJob`, `TenantImportJob`, `DataRetentionPolicy`, `DataSubjectRequest` with PostgreSQL RLS enabled (`0008`, `0009`, `0010`).
    - Domain Services:
      - Export: Streams all tenant entities (catalog, customers, suppliers, inventory, sales, purchases, invoices, payments, journals, employees, webhooks) to a structured archive with SHA-256 integrity checksums.
      - Import: Validates manifest and organization boundary, imports catalog items, price lists, customer records, and addresses with collision detection and rollback on error.
      - Data Retention: Configurable retention periods for audit logs, webhook deliveries, export jobs, and customer activity logs with automated Celery cleanup task.
      - GDPR Compliance: Export of all data subject personal records, and erasure workflow with customer PII pseudonymization while keeping immutable financial transaction histories.
    - Web UI & HTMX: Portability overview (`/integrations/portability/`), export launcher & detail view (`/integrations/portability/exports/<id>/`), import upload & status tracker, retention policy configuration (`/integrations/retention/`), and data subject request processing dashboard.
    - REST API: Versioned endpoints under `/api/v1/integrations/portability/` (exports, imports, retention-policy, data-subject-requests) with OpenAPI schema definitions.
    - Test Suite: 9 tests in `test_data_portability_and_compliance.py`, 83/83 passing in `apps/integrations/tests/`.
  - Next task: P5-08 Notifications center (in-app + email), user notification preferences.

