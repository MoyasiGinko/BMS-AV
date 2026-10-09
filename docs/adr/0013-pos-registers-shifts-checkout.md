# 0013. Point of Sale (POS) Architecture, Registers, Shifts, and Fast Checkout

## Context
Task P2-06 specifies the Point of Sale module (`apps.pos`) for physical counter sales and retail checkout:
1. POS Registers (terminals) assigned to branches and default warehouses.
2. Cashier Shifts: session management with cash drawer open count, closed count, expected cash tracking, and variance calculation.
3. Fast checkout screen: 2-pane layout (product search/barcode scanner input + category quick-keys on left; cart with quantity steppers, discounts, tax, customer picker, hold/resume cart, and tender modal with split payments on right).
4. Atomicity and ledger integration: checkout reuses `apps.sales` services (`create_invoice`, `post_invoice`, and `receive_payment`) to guarantee identical, single-source-of-truth stock issues, COGS journals, tax postings, and cash/bank accounting entries.
5. Printable and downloadable POS receipts.

## Decision
1. Module structure: `apps/pos/` containing `models.py`, `services.py`, `selectors.py`, `events.py`, `permissions.py`, `forms.py`, `views.py`, `urls.py`, `admin.py`, `api/`, `templates/pos/`, and `tests/`.
2. Core Models (all inheriting `TenantModel` with Row-Level Security):
   - `POSRegister`: register code, name, branch, warehouse, receipt header/footer, active status.
   - `POSShift`: register, cashier (`User`), status (`OPEN`, `CLOSED`), opened_at, closed_at, opening_cash, closing_cash_counted, expected_cash, cash_variance, total_sales, total_returns, total_cash_collected, total_card_collected, notes.
   - `POSHeldCart`: held carts for parking and resuming transactions.
   - `POSSale`: link between POS shift, register, cashier, and the underlying `sales.Invoice` and `sales.Payment`s.
3. Atomic checkout service (`services.checkout_pos_sale`):
   - Verifies active open shift on the register and open fiscal period.
   - Validates cart line items, calculates discounts, taxes, and grand total.
   - Calls `sales_services.create_invoice` + `sales_services.post_invoice` to issue stock from register warehouse and post GL revenue, tax, and COGS journals.
   - Calls `sales_services.receive_payment` for each tender (cash, card, split payments) to debit cash/bank accounts and credit AR.
   - Updates shift totals (`total_sales`, `total_cash_collected`, `total_card_collected`, `expected_cash`).
   - Emits `POSSaleCompleted` domain event.
4. Shift management services:
   - `open_shift`: opens a shift with starting cash float.
   - `close_shift`: closes the shift with counted cash drawer amount, computes `cash_variance = closing_cash_counted - expected_cash`, posts a cash variance journal entry if non-zero, and marks shift closed.

## Consequences
- Single accounting and stock engine: zero drift between backoffice sales and POS register sales.
- Cash audit trail: cash variance is tracked per shift and posted to cash over/short GL account.
- Complete fast checkout UX with barcode scanning, quick keys, and responsive layout.
