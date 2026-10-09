# Build State (updated by the agent after every task)

- Phase: P2 Small-shop MVP (in progress)
- Last completed task: P2-11
- Next task: P2-R
- Open `[!]` tasks: none
- Last `make verify`: PASSED (88.16% test coverage, 436 tests green, all architecture contracts kept, openapi valid, deploy check clean)
- Notes: P2-11 implemented seed_demo command for "Small Shop" org and comprehensive end-to-end business cycle tests (governed by ADR 0018 and ADR 0019):
  - Demo Seeding Command: `python manage.py seed_demo --target small_shop` (and `--reset`) provisions "Artisan Bakery & Cafe" (`small-shop`) on the starter plan with standard users (`demo12345`), chart of accounts, fiscal calendar, products catalog, warehouses, stock levels, customers, POS registers/shifts/sales, and B2B quote-to-invoice workflows with partial payments.
  - End-to-End Business Flow Suite: `tests/e2e/test_small_shop_e2e.py` validates the complete life-cycle of a small business: counter POS checkout (split tenders, real-time stock decrement, receipt numbering), B2B quote -> sales order -> posted invoice -> stock dispatch, payment receipt with ledger/invoice allocation, and invariant checks ensuring stock ledger movements match on-hand quantities.
  - Quality Gate: Full verify-win passed cleanly with 436 tests passing, 88.16% test coverage, 0 mypy/ruff/django/contract issues.
  - Next task: P2-R Phase review: `/verify` + `/review-module` for each module.
