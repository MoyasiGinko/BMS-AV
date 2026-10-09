# Build State (updated by the agent after every task)

- Phase: P2 Small-shop MVP (in progress)
- Last completed task: P2-09
- Next task: P2-10
- Open `[!]` tasks: none
- Last `make verify`: PASSED (87.94% test coverage, 427 tests green, all architecture contracts kept, openapi valid, deploy check clean)
- Notes: P2-09 implemented Import/Export framework (governed by ADR 0016):
  - Architecture: Unified `ImportJob` and `ExportJob` models in new `apps.integrations` module with PostgreSQL RLS and tenant scoping.
  - Lifecycle: Multi-step validate-preview-commit workflow (UPLOADED -> VALIDATING -> VALIDATED -> COMMITTING -> COMPLETED / FAILED) with row error reports and dry-run preview before DB changes.
  - Importers & Exporters: Unified `BaseEntityImporter` and `BaseEntityExporter` engines supporting CSV (RFC 4180 with utf-8-sig encoding and BOM detection) and styled Excel XLSX (`openpyxl`), with automated dynamic blank template generation.
  - Domain Adapters: `ProductImporter` and `CustomerImporter` (and corresponding exporters) wrapping core domain services with duplicate detection, price validation, category/unit auto-creation, address/contact child parsing, and configurable options (`update_existing`, `create_missing`).
  - UI & HTMX: Central data imports hub, export downloads center, entity upload screens with progress polling, validation error breakdown tables, and 20-row sample preview screens with HTMX commit triggers.
  - Quality Gate: Full verify-win passed cleanly with 427 tests passing, 87.94% test coverage, 0 mypy/ruff/django/contract issues.
  - Next task: P2-10 Public API v1 for P2 modules (catalog, inventory, customers, sales, pos) fully documented in OpenAPI with idempotency on sales/payments.
