# Build State (updated by the agent after every task)

- Phase: P5 ERP maturity
- Last completed task: P5-02 Advanced inventory: batches/expiry, serials, FIFO costing strategy, reorder suggestions, stock count workflow
- Next task: P5-03 Approvals engine: configurable approval rules (PO over X, expense over Y, payroll, discounts) with inbox UI
- Open `[!]` tasks: none
- Last `make verify`: PASSED (9/9 advanced inventory tests passing, 60/60 tests across inventory and purchasing passing, ruff lint and format clean, lint-imports clean)
- Notes:
  - P5-02 Complete: Advanced inventory with batches, serials, FIFO costing, reorder suggestions, and stock count workflow:
    - Batches & Expiry: `Batch` and `BatchStock` models, FEFO auto-allocation on issue, expiry validation (`BatchExpiredError`), expiring batch detection (`get_expiring_batches`).
    - Serials: `SerialNumber` model with `SerialStatus` (`in_stock`, `issued`, etc.), serialized intake registration, issue validation/marking, serial number lookup.
    - FIFO Costing: `FIFOCostingStrategy` and `StockCostLayer` model, chronological layer creation on intake, FIFO layer consumption on issue, dynamic remaining average cost updating, integration with `OrganizationSettings.costing_method == 'fifo'`.
    - Reorder Suggestions: `get_reorder_suggestions` selector computing low stock items, suggested reorder quantities, and estimated cost; `create_purchase_orders_from_reorder_suggestions` in `apps/purchasing/services.py` grouping suggestions by supplier into draft POs.
    - Stock Count Workflow: `start_stock_count` (Draft -> In Progress), `record_stock_count_progress` (variance tracking), `complete_stock_count` (auto-creates and confirms `StockAdjustment` with `AdjustmentReason.COUNT_VARIANCE` and links `count.adjustment`).
    - Web Views & Templates: batch list/detail, serial list/detail, reorder suggestions list (with quick action to draft POs), cycle count start/progress/complete actions.
  - Next task: P5-03 Approvals engine: configurable approval rules (PO over X, expense over Y, payroll, discounts) with inbox UI.
