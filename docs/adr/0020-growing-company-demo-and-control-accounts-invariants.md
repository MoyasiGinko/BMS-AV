# ADR 0020: Growing Company Demo Seeding and Control Account Invariants

## Status
Accepted

## Context
Per P3-07 in `docs/BACKLOG.md` and `docs/04-testing-and-validation.md`, the platform requires:
1. Extension of the `seed_demo` management command to provision the "Growing Company" organization (`Apex Industrial Wholesale`, slug `growing-company`, plan `growth`) featuring multi-branch/multi-warehouse operations, realistic B2B purchasing (POs, goods receipts, supplier bills, disbursements), B2B sales (quotes, orders, posted invoices, payments, recurring profiles), and chart of accounts.
2. Invariant verification ensuring that the subsidiary ledgers (Accounts Receivable, Accounts Payable, and Inventory on-hand valuation) reconcile exactly to their general ledger control accounts (1100 AR, 2000 AP, 1200 Inventory Asset).
3. Inclusion of `apps.purchasing` in the `seed_demo` command, requiring extending the `ignore_imports` list in `pyproject.toml` per ADR 0019.

## Decision
1. Add `seed_growing_company` to `apps/core/management/commands/seed_demo.py` with multi-role credentials (`owner`, `sales`, `buyer`, `accountant`, `warehouse` @apexwholesale.com, password `demo12345`), multi-warehouse stock, supplier bills, sales orders, recurring invoices, and payment reminders.
2. Allow `--target growing_company` in `seed_demo` CLI argument.
3. Add `apps.core.management.commands.seed_demo -> apps.purchasing.models` and `apps.purchasing.services` to `ignore_imports` in `pyproject.toml`.
4. Implement `tests/invariants/test_control_account_reconciliation.py` to assert mathematical equality between subledgers and control accounts across both synthetic property tests and the seeded demo organization.

## Consequences
- Immediate evaluation capability for the entire P1-P3 suite via `python manage.py seed_demo --target growing_company`.
- Strong guarantees against subledger drift in Accounts Receivable, Accounts Payable, and Inventory Asset.
- Verification gates and architectural layering contracts remain strictly enforced.
