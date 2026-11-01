# ADR 0019: Import-Linter Exemption for seed_demo Management Command

## Status
Accepted

## Context
The `seed_demo` management command (`python manage.py seed_demo`) is the platform-wide CLI entry point (invoked by `make seed` and E2E evaluation) for provisioning and populating realistic multi-tenant demonstration data across all apps (accounts, tenancy, billing, catalog, inventory, customers, POS, sales, and accounting).
Because Django discovers management commands within registered apps, the command was placed under `apps.core.management.commands.seed_demo`.
However, `import-linter` enforces a strict module hierarchy where `apps.core` is the foundational layer and is forbidden from importing upper-level modules. As an orchestration tool for the entire application, `seed_demo` necessarily imports services and models from multiple domain apps.

## Decision
Add explicit exemptions to `ignore_imports` in `pyproject.toml` under the "Module layering" contract for `apps.core.management.commands.seed_demo` importing domain modules (`apps.accounts`, `apps.accounting`, `apps.billing`, `apps.catalog`, `apps.customers`, `apps.inventory`, `apps.pos`, `apps.sales`, `apps.tenancy`).

## Consequences
- `apps.core` foundational library code (middleware, models, RLS, audit, outbox, number sequence) remains strictly isolated and forbidden from importing domain apps.
- The `seed_demo` CLI command can cleanly and statically orchestrate the entire platform data lifecycle without obfuscated dynamic imports.
- `make verify` and `lint-imports` pass with 100% integrity across all architectural layers.
