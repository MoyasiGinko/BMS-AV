# 18. Demo Seeding Engine and Small-Shop E2E Story

Date: 2026-10-10

## Context
As specified in `docs/04-testing-and-validation.md` and `docs/BACKLOG.md` (P2-11), the platform must provide a `seed_demo`
Django management command (`make seed`) enabling immediate click-through evaluation and comprehensive E2E testing.
The evaluator must be able to log in with known credentials (`demo12345`), inspect an operational small shop with realistic
catalog items, positive stock, historical invoices, customer balances, and completed POS counter checkouts.

## Decision
1. **Command Architecture**: Implemented `python manage.py seed_demo` under `apps/core/management/commands/seed_demo.py`.
   Accepts an optional `--target` argument (e.g. `small_shop`, `all`) allowing incremental addition of future demo targets
   (P3-07 Growing Company, P4-06 Full ERP). Default seeds all available targets.
2. **Small Shop Entity Specification**:
   - Organization: "Artisan Bakery & Cafe" (slug `small-shop`, plan `starter`).
   - Users: `owner@artisanbakery.com`, `cashier@artisanbakery.com`, `accountant@artisanbakery.com` (password `demo12345`).
   - Catalog: Categories ("Pastries", "Hot Beverages", "Cold Beverages", "Retail Goods"), Units ("pcs", "kg", "box"),
     realistic items (Croissant, Sourdough, Espresso, Cold Brew, Coffee Beans, Ceramic Mug) with standard tax codes (VAT 10%).
   - Stock: Realistic inventory received into default warehouse so levels are immediately available for counter checkout and orders.
   - POS: "Front Counter 1" terminal, active and completed cashier shifts, counter transactions with split tenders (cash & card).
   - Invoicing: Customers ("Acme Office Hub", "Metropolitan Bistro"), quotes, orders, posted invoices, and payments.
   - Idempotent: Can be run multiple times safely without duplicate key violations or conflicting ledgers.
3. **End-to-End Validation**: Created `tests/e2e/test_small_shop_e2e.py` testing the complete operational flow across
   POS sales, B2B order-to-invoice dispatch, payment allocation, and ledger/stock reconciliation.

## Consequences
- Developers and evaluators can spin up a fully populated environment instantly via `make seed`.
- E2E tests validate cross-module cohesion between catalog, inventory, sales, POS, and accounting.
