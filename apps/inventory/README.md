# Inventory Module (`apps.inventory`)

Warehouse management, real-time stock levels, ledger-driven stock movements, transfers, adjustments, and valuation.

## Responsibilities
- **Inventory Ledger Primitives**: `Warehouse`, `StockLevel`, `StockMovement`, `StockAdjustment`, `StockTransfer`.
- **Atomic Stock Invariant**: Real-time `StockLevel.on_hand` is locked (`select_for_update`) during mutations and guaranteed to equal the sum of historical immutable `StockMovement` records.
- **Costing & Valuation**: Moving average costing engine (`calculate_moving_average_cost`) with decimal arithmetic.
- **Immutability**: Stock movements are append-only. Corrections require compensating reversal movements.
- **Transactional Services**:
  - `receive_stock`: Goods receipt with unit costing.
  - `dispatch_stock`: Outbound stock issue with cost depletion and validation against negative inventory.
  - `adjust_stock`: Physical count reconciliation with automatic general ledger postings.
  - `transfer_stock`: Multi-warehouse transit and receipt.
- **Domain Events**: Publishes `inventory.stock_received`, `inventory.stock_dispatched`, `inventory.stock_adjusted`, `inventory.stock_transferred`.
- **Interfaces**:
  - Full HTMX UI: warehouse list, live stock balance dashboard, stock movement history, adjustments workflow.
  - REST API v1 (`/api/v1/inventory/stock-levels/`, `/api/v1/inventory/movements/`, `/api/v1/inventory/adjustments/`): OpenAPI documented.
- **Permissions**: Three-layer security checks (`inventory` module entitlement, role permissions, tenant scope).
