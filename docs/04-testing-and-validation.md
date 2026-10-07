# Testing & Validation Specification

| Layer | Location | Tools | Must prove |
|---|---|---|---|
| Unit | `apps/*/tests/test_services*.py` | pytest, factory_boy | rules, calculators (tax, costing, payroll), state machines |
| Integration | `tests/integration/` | pytest-django | sale->stock->ledger->balance; purchase->payable; payroll->accounting; plan limits |
| API contract | `apps/*/tests/test_api_*.py` | DRF client | auth, scopes, pagination, errors, idempotency, schema |
| Tenant isolation | `tests/architecture/`, per-feature | pytest | no cross-org access (UI/API/export/task/RLS) |
| Invariants | `tests/invariants/` | hypothesis | debits==credits; stock==ledger; AR/AP/inventory subledgers==control accounts; trial balance; report totals==ledger |
| E2E story | `tests/e2e/test_business_story.py` | pytest + client | full business story (see `.agent/workflows/final-audit.md`) |
| UI smoke | `tests/ui/` (`-m ui`) | Playwright | signup, login, product, POS checkout, invoice, dashboard render, no console errors |
| Performance | `tests/perf/` | pytest + query counts | POS checkout < 300 ms locally, dashboards constant queries |

Gates (all in `scripts/verify.sh`): ruff, ruff format, mypy, migrations in sync, `manage.py check`, import-linter, pytest with coverage >= 80%
(ratchet up as the project grows), OpenAPI validation, `check --deploy`.

`seed_demo` management command creates 3 demo orgs (small shop, growing company, full ERP) with users for every role (password `demo12345`), realistic
catalog, 6 months of sales/purchases/expenses/payroll, so the human evaluator can click through everything immediately.
