# Business OS: Agent Operating Manual

Antigravity reads this file (and GEMINI.md). Keep it short. Details live in `docs/` and `.agent/`.

## Mission
Build the COMPLETE multi-tenant SaaS Business Management Platform (ERP) specified in `docs/`.
Django full-stack (server-rendered templates + HTMX) is the product. A versioned DRF REST API, webhooks and a
connector framework are an additive layer over the same service layer. Done = every item in `docs/BACKLOG.md` is `[x]`
and `make verify` passes.

## Autonomy contract (non-negotiable)
1. NEVER ask the user for confirmation, approval, clarification or preferences. Nobody is watching. Decide, record, continue.
2. Ambiguity: pick the option documented in `docs/`; if none, pick the simplest option consistent with the architecture rules,
   write a 5-line ADR in `docs/adr/NNNN-title.md`, continue.
3. Never stop until the backlog is complete. Work the loop in `.agent/workflows/build-all.md`.
4. Never weaken a gate to get green: no deleting/skipping tests, no lowering thresholds, no `# noqa`/`type: ignore` blanket use,
   no editing `scripts/verify.sh`, `pyproject.toml` lint/test config or `tests/architecture/` without an ADR justifying it.
5. External credentials/services you cannot have (payment gateway, SMS, etc.): implement behind an adapter with a fake/sandbox
   implementation, log it in `docs/BLOCKERS.md`, move on.
6. Persist progress in `.agent/STATE.md` and `docs/BACKLOG.md` after EVERY task so a fresh session can resume with `/build-all`.

## Stack (fixed; do not re-debate)
Python 3.12, Django 5.x, PostgreSQL 16, Redis, Celery, DRF + drf-spectacular, HTMX + Alpine.js + Tailwind (standalone CLI, no Node
required), pytest, ruff, mypy (django-stubs), import-linter, factory_boy, hypothesis, Playwright (UI smoke).

## Commands
- `make setup`    install deps, start db/redis (docker or local), migrate
- `make verify`   THE gate (lint, types, migrations, architecture, tests, schema, deploy check). Must pass before any task is done.
- `make run`      dev server;  `make seed`  demo data;  `make worker`  celery

## Read before you code (progressive disclosure)
| Working on | Read |
|---|---|
| anything | `docs/01-architecture.md`, `.agent/rules/*` |
| models/fields | `docs/02-domain-model.md` |
| UI | `docs/design/design-system.md`, `docs/design/reference/reference-screens.html` (open it to see the target look), skill `htmx-screen` |
| API/integrations | `docs/03-api-and-integrations.md`, skill `drf-endpoint` |
| money/stock | skill `ledger-posting`, rule `30-accounting-inventory` |
| tests | `docs/04-testing-and-validation.md` |

## Hard rules (the ten that are always on)
1. Business logic only in `apps/<app>/services.py`; reads in `selectors.py`. Views/serializers/tasks/admin call services.
2. Every tenant model inherits `TenantModel` and uses the scoped manager. Unique constraints and indexes start with `organization`.
3. Money/quantity = `Decimal` (`DecimalField`), never float.
4. Posted financial/stock records are immutable; corrections are reversals.
5. Every state change of a document is one `transaction.atomic` service that also publishes a domain event (outbox).
6. Cross-module imports follow the layer contract in `pyproject.toml` (enforced by import-linter).
7. Three permission layers on every entry point: plan entitlement, role permission, object scope.
8. Every endpoint/screen/service ships with tests (success, permission denied, cross-tenant isolation, rollback).
9. API is additive and versioned (`/api/v1/`), OpenAPI must validate; no business rules in serializers.
10. UI follows `docs/design/design-system.md`; every screen has empty/loading/error states.
