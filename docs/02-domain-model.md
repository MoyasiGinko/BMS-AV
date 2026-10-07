# Domain Model (authoritative entity list)

All tenant models inherit `TenantModel` (organization, created_at, updated_at, created_by) and have `public_id` UUID. Money = Decimal(18,4).

## accounts / tenancy / billing
- `User(email, name, locale, tz, is_active, totp_secret?)` (global). `Organization(name, slug, base_currency, country, tz, fiscal_year_start, settings JSON)` (global).
- `Membership(user, organization, role, is_owner, status)`; `MembershipBranch(membership, branch)`; `Role(organization, name, permissions[])`; `Invitation(email, role, token, expires_at)`.
- `Branch`, `Department`, `Warehouse(branch, code, is_default)`, `OrganizationSettings(allow_negative_stock, costing_method, tax_inclusive, number formats...)`.
- `Plan(key, name, price, interval, limits JSON)`, `Module(key, label)` + `PlanModule`, `Subscription`, `UsageCounter`, `PaymentRecord(provider_ref, status)`.
- `ApiKey(prefix, hash, scopes, expires_at, last_used_at)`, `AuditLog(actor, action, object_ref, before, after, ip)`.

## catalog
`Category(parent)`, `Unit`, `UnitConversion`, `TaxCode(rate, inclusive)`, `Product(sku, barcode, name, category, unit, type[stock|service|bundle], cost, price, tax_code, track_batch, track_serial, reorder_level, reorder_qty, is_active)`,
`ProductVariant`, `PriceList`, `PriceListItem`, `ProductImage`.

## inventory
`StockMovement(product, warehouse, qty±, unit_cost, type, reference_type/id, occurred_at, batch?)` (immutable), `StockLevel(product, warehouse, on_hand, reserved, avg_cost)`,
`StockReservation`, `StockTransfer(+lines)`, `StockAdjustment(+lines, reason)`, `StockCount(+lines)`, `Batch`, `SerialNumber`.

## purchasing
`Supplier(+balance)`, `PurchaseOrder(+lines, status)`, `GoodsReceipt(+lines)`, `SupplierBill(+lines, due_date)`, `SupplierPayment(+allocations)`, `PurchaseReturn`.

## sales / pos / customers
`Customer(code, type, credit_limit, balance, price_list, tax_id)`, `CustomerAddress`, `CustomerContact`,
`Quote`, `SalesOrder(+lines)`, `Invoice(+lines, number, due_date, status[draft|posted|partially_paid|paid|void])`, `CreditNote`, `Receipt/CustomerPayment(+allocations)`,
`Sale` (unifies order/POS sale: branch, warehouse, customer, lines, discounts, totals),
`PosRegister`, `PosShift(opened_by, opening_cash, closing_cash, variance)`, `PosSale(sale, register, shift, tenders)`, `Tender(method, amount)`, `PaymentMethod`.
CRM: `Lead`, `Opportunity(stage, value)`, `Pipeline/Stage`, `Interaction(type, notes, due)`, `Task`, `Tag`.

## accounting
`Account(code, name, type, parent, is_control)`, `AccountMapping(key -> account)`, `FiscalYear`, `FiscalPeriod(status)`,
`JournalEntry(date, memo, source_type/id, status, reversed_by)`, `JournalLine(entry, account, debit, credit, currency, base_amount, fx_rate, party?)`,
`Payment` (generic cash/bank movement), `BankAccount`, `Expense(+category, vendor, receipt)`, `ExpenseCategory`, `Currency`, `ExchangeRate`, `TaxReturnSummary`.

## hr / payroll
`Employee(code, user?, branch, department, position, hire_date, status, bank & national id encrypted)`, `Position`, `Shift`, `AttendanceRecord(check_in, check_out, source)`,
`LeaveType`, `LeaveBalance`, `LeaveRequest`, `SalaryStructure(+components)`, `PayrollRun(period, status)`, `Payslip(+lines)`, `PerformanceReview`.

## reports / automation / integrations / ai
`SavedReport`, `ReportSchedule`, `DailySalesSummary`, `DailyExpenseSummary`, `DashboardLayout`,
`AutomationRule`, `AutomationRun`, `Notification`, `OutboxEvent`, `WebhookEndpoint`, `WebhookDelivery`, `InboundEvent`, `IntegrationConnection`, `ExternalReference`, `ImportJob`, `ExportJob`, `IdempotencyRecord`,
`AiConversation`, `AiMessage`, `AiAuditLog`.

## Default permission codes (seed into roles Owner, Admin, Manager, Cashier, Accountant, HR, Viewer)
`<module>.view|create|update|delete|approve|export` plus specials: `sales.confirm`, `sales.void`, `pos.open_shift`, `pos.refund`, `inventory.adjust`, `accounting.post`, `accounting.close_period`,
`payroll.run`, `payroll.approve`, `settings.manage`, `users.manage`, `api_keys.manage`, `integrations.manage`, `ai.use`.
