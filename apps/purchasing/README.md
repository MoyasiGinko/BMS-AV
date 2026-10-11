# Purchasing Module (`apps.purchasing`)

Procurement, vendor management, supplier billing, and accounts payable engine for Business OS.

## Responsibilities
- **Vendor Management**: `Supplier` with contact person, payment terms, currency, balance ledger, and address book.
- **Purchase Orders**: `PurchaseOrder` and `PurchaseOrderLine` supporting multi-line order drafting, approval workflows (`approve_purchase_order`), and cancellation.
- **Goods Receipt**: `GoodsReceipt` and `GoodsReceiptLine` receiving physical stock into destination warehouses at unit cost prices via `inventory_services.receive_stock`. Automatically marks linked PO as received upon fulfillment.
- **Supplier Bills**: `SupplierBill` and `SupplierBillLine` recording vendor accounts payable invoices with due dates, linked to POs and Goods Receipts. Posts double-entry journal entries (`Dr inventory.asset`, `Dr tax.input`, `Cr ap`) and updates supplier `current_balance`.
- **Disbursements / Payments**: `SupplierPayment` and `SupplierPaymentAllocation` settling bills via cash or bank transfers, updating general ledger accounts (`Dr ap`, `Cr bank/cash`) and reducing supplier balances.
- **Purchase Returns**: `PurchaseReturn` and `PurchaseReturnLine` returning received goods back to vendors, debiting vendor AP balance and relieving physical inventory stock.
- **Transactional Outbox Events**: Publishes `PurchaseOrderCreated`, `GoodsReceiptReceived`, `SupplierBillPosted`, `SupplierPaymentRecorded`, and `PurchaseReturnPosted` domain events.
- **Versioned REST API**: Complete DRF endpoints under `/api/v1/purchasing/` with OpenAPI specification, tenant scoping, and permission enforcement.
