# 0009. Inventory Ledger, Costing Strategy, and Stock Levels

Date: 2026-10-08

## Context
Phase P2 requires an operational inventory ledger for retail and multi-warehouse operations.
Stock must be tracked accurately with strict `Decimal(18, 4)` precision. Financial and operational
integrity requires:
1. An immutable stock ledger (`StockMovement`) recording every inventory event (receipts, issues,
   transfers, adjustments, returns).
2. A high-performance cache (`StockLevel`) tracking `on_hand`, `reserved`, and weighted average cost.
3. Pluggable costing strategies (`CostingStrategy`, starting with `WeightedAverageCostingStrategy`).
4. Strict cross-warehouse transfers (two linked movements) and reason-coded adjustments.
5. Cycle counts with automated variance reconciliation into adjustments.
6. Negative stock prevention by default, with tenant configuration override.
7. Periodic and on-demand reconciliation job comparing ledger sums against cached levels.

## Decision
1. **Immutable Ledger & Cache Architecture**:
   - `StockMovement` records signed quantity, unit cost, total cost, reference type/ID, and timestamp. Movements cannot be modified or deleted.
   - `StockLevel` is scoped by `(organization, warehouse, product, variant)` with `select_for_update` row-level locks on all mutating operations.
   - Available stock is calculated as `max(0, on_hand - reserved)`.
2. **Costing**:
   - `WeightedAverageCostingStrategy` recalculates `avg_cost` on positive movements (`new_avg_cost = ((on_hand * avg_cost) + (new_qty * unit_cost)) / (on_hand + new_qty)`).
   - Issues and outbound transfers consume stock at the current `avg_cost`.
3. **Reservations & Operations**:
   - `StockReservation` holds available stock for sales orders or POS holds without moving physical stock until fulfillment.
   - `StockTransfer` issues from source warehouse (`TRANSFER_OUT`) and receives into destination warehouse (`TRANSFER_IN`).
   - `StockAdjustment` records adjustments with mandatory reason codes (`damage`, `spoilage`, `shrinkage`, `count_variance`, `correction`).
4. **Reconciliation Job**:
   - `reconcile_inventory` computes `SUM(quantity)` from `StockMovement` per product/warehouse and verifies equality with `StockLevel.on_hand`. Discrepancies can be auto-corrected with audit logs.

## Consequences
- Guarantees complete auditability of all inventory changes.
- Eliminates race conditions via row locks and transaction atomicity.
- Provides seamless integration for upcoming sales orders, POS checkouts, and purchase receipts.
