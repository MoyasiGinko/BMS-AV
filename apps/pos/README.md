# Point of Sale Module (`apps.pos`)

High-speed retail counter checkout, register hardware configuration, cashier shift balancing, split tenders, receipt generation, and real-time stock sync.

## Responsibilities
- **Register & Shift Management**:
  - `POSRegister`: Terminal binding, warehouse allocation, receipt header/footer templates.
  - `POSShift`: Cashier session tracking with opening float, running tender totals, and closing cash count with discrepancy variance tracking.
- **Sales Transactions**:
  - `POSSale` & `POSSaleLine`: Fast barcode lookup, category tiles, instant quantity editing, discount handling, and receipt numbering (`REC-YYYYMMDD-XXXX`).
  - `POSPayment`: Split tender support (cash, credit/debit card, bank transfer, store credit).
- **Atomic Checkout & Invariants**:
  - `checkout_pos_sale`: Validates open shift, decrements warehouse inventory in real-time, records double-entry accounting revenue postings, and links walk-in or loyalty customers.
- **Interfaces**:
  - Fast-action HTMX/Alpine POS UI: touch-friendly keypad, category quick-filters, basket drawer, split-payment tender modal, and print receipt view.
  - REST API v1 (`/api/v1/pos/registers/`, `/shifts/`, `/sales/`): Idempotent checkout and shift management.
- **Domain Events**: Publishes `pos.shift_opened`, `pos.sale_completed`, `pos.shift_closed`.
- **Permissions**: Scoped by plan entitlement (`pos` module), role (`pos.operate_register`, `pos.manage_registers`), and active assigned branches.
