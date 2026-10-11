"""Control Account vs Subledgers Reconciliation Invariant Tests.

Verifies mathematical reconciliation across:
1. Accounts Receivable (AR): sum(Customer.balance) == sum(Invoice.balance_due) == Account 1100.
2. Accounts Payable (AP): sum(Supplier.balance) == sum(SupplierBill.balance_due) == Account 2000.
3. Inventory Asset: physical on-hand valuation == Account 1200 balance.
4. General Ledger: total debits == total credits (Trial Balance balanced).

Verified on:
- Seeded 'Apex Industrial Wholesale' (growing-company) demo organization.
- Seeded 'Artisan Bakery & Cafe' (small-shop) demo organization.
- Synthetic multi-transaction lifecycle with Hypothesis property-based testing.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import pytest
from django.core.management import call_command
from django.db.models import Sum
from django.utils import timezone
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.accounting.selectors import (
    get_account_balance,
    get_account_by_code,
    get_trial_balance,
    resolve_mapped_account,
)
from apps.accounting.services import Cr, Dr, post_entry, seed_chart_of_accounts, seed_fiscal_calendar
from apps.accounts.models import User
from apps.catalog.models import Category, Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.customers import services as customers_services
from apps.customers.models import Customer
from apps.inventory.models import StockLevel
from apps.purchasing import services as purchasing_services
from apps.purchasing.models import (
    Supplier,
    SupplierBill,
    SupplierBillStatus,
    SupplierPaymentMethod,
)
from apps.reports import selectors as reports_selectors
from apps.sales import services as sales_services
from apps.sales.models import Invoice, InvoiceStatus, PaymentMethod
from apps.tenancy.models import Branch, Organization, TaxCode, Warehouse
from apps.tenancy.services import provision_organization

DECIMAL_ZERO = Decimal("0.0000")
FOUR_PLACES = Decimal("0.0001")


@pytest.fixture
def clean_demo_environment(db: None) -> None:
    """Ensure both demo organizations are fresh before running invariant verifications."""
    call_command("seed_demo", "--target", "all", "--reset")


@pytest.mark.django_db(transaction=True)
def test_growing_company_demo_control_accounts_reconciliation(
    clean_demo_environment: None,
) -> None:
    """Invariant: Apex Industrial Wholesale (growing-company) control accounts reconcile with subledgers."""
    org = Organization.objects.filter(slug="growing-company").first()
    assert org is not None, "Organization 'growing-company' must be seeded."

    with tenant_context(org):
        # 1. Accounts Receivable (AR) Invariant: Code 1100
        ar_account = get_account_by_code(organization_id=org.pk, code="1100")
        assert ar_account is not None, "Control Account 1100 (AR) must exist."

        gl_ar_balance = get_account_balance(organization_id=org.pk, account_id=ar_account.pk)
        customer_subledger_total = (
            Customer.all_tenants.filter(organization=org).aggregate(tot=Sum("current_balance"))["tot"]
            or DECIMAL_ZERO
        )
        invoice_unpaid_total = (
            Invoice.all_tenants.filter(
                organization=org,
                status__in=[
                    InvoiceStatus.POSTED,
                    InvoiceStatus.PARTIALLY_PAID,
                ],
            ).aggregate(tot=Sum("balance_due"))["tot"]
            or DECIMAL_ZERO
        )

        assert customer_subledger_total > DECIMAL_ZERO, "Must have active receivables."
        assert gl_ar_balance == customer_subledger_total, (
            f"GL AR ({gl_ar_balance}) != Customer Subledger ({customer_subledger_total})"
        )
        assert customer_subledger_total == invoice_unpaid_total, (
            f"Customer Subledger ({customer_subledger_total}) != Invoice Unpaid Due ({invoice_unpaid_total})"
        )

        # 2. Accounts Payable (AP) Invariant: Code 2000
        ap_account = get_account_by_code(organization_id=org.pk, code="2000")
        assert ap_account is not None, "Control Account 2000 (AP) must exist."

        gl_ap_balance = get_account_balance(organization_id=org.pk, account_id=ap_account.pk)
        supplier_subledger_total = (
            Supplier.all_tenants.filter(organization=org).aggregate(tot=Sum("current_balance"))["tot"]
            or DECIMAL_ZERO
        )
        bill_unpaid_total = (
            SupplierBill.all_tenants.filter(
                organization=org,
                status__in=[
                    SupplierBillStatus.POSTED,
                    SupplierBillStatus.PARTIALLY_PAID,
                ],
            ).aggregate(tot=Sum("balance_due"))["tot"]
            or DECIMAL_ZERO
        )

        assert supplier_subledger_total > DECIMAL_ZERO, "Must have active payables."
        assert gl_ap_balance == supplier_subledger_total, (
            f"GL AP ({gl_ap_balance}) != Supplier Subledger ({supplier_subledger_total})"
        )
        assert supplier_subledger_total == bill_unpaid_total, (
            f"Supplier Subledger ({supplier_subledger_total}) != Bill Unpaid Due ({bill_unpaid_total})"
        )

        # 3. Inventory Asset Invariant: Code 1200
        inv_account = get_account_by_code(organization_id=org.pk, code="1200")
        assert inv_account is not None, "Control Account 1200 (Inventory Asset) must exist."

        gl_inventory_balance = get_account_balance(organization_id=org.pk, account_id=inv_account.pk)

        stock_levels = StockLevel.all_tenants.filter(organization=org).select_related("product")
        calculated_stock_valuation = sum(
            (sl.on_hand * sl.product.cost_price).quantize(FOUR_PLACES) for sl in stock_levels
        )

        stock_report = reports_selectors.get_stock_valuation_report(organization=org)
        reported_stock_valuation = stock_report["summary"]["total_valuation"]

        assert gl_inventory_balance > DECIMAL_ZERO, "Must have active inventory asset."
        assert calculated_stock_valuation == reported_stock_valuation, (
            f"Calculated ({calculated_stock_valuation}) != Reported Valuation ({reported_stock_valuation})"
        )
        assert gl_inventory_balance == calculated_stock_valuation, (
            f"GL Inventory ({gl_inventory_balance}) != Stock Subledger ({calculated_stock_valuation})"
        )

        # 4. General Ledger Trial Balance Invariant: Debits == Credits
        tb = get_trial_balance(organization_id=org.pk)
        assert tb["is_balanced"] is True, "General Ledger Trial Balance must be balanced."
        assert tb["total_debit"] == tb["total_credit"], "Total Debits must equal Total Credits."
        assert tb["total_debit"] > DECIMAL_ZERO, "Trial balance debits must be non-zero."


@pytest.mark.django_db(transaction=True)
def test_small_shop_demo_control_accounts_reconciliation(
    clean_demo_environment: None,
) -> None:
    """Invariant: Artisan Bakery & Cafe (small-shop) control accounts reconcile with subledgers."""
    org = Organization.objects.filter(slug="small-shop").first()
    assert org is not None, "Organization 'small-shop' must be seeded."

    with tenant_context(org):
        # 1. Accounts Receivable (AR) Invariant
        ar_account = get_account_by_code(organization_id=org.pk, code="1100")
        assert ar_account is not None

        gl_ar_balance = get_account_balance(organization_id=org.pk, account_id=ar_account.pk)
        customer_subledger_total = (
            Customer.all_tenants.filter(organization=org).aggregate(tot=Sum("current_balance"))["tot"]
            or DECIMAL_ZERO
        )
        invoice_unpaid_total = (
            Invoice.all_tenants.filter(
                organization=org,
                status__in=[
                    InvoiceStatus.POSTED,
                    InvoiceStatus.PARTIALLY_PAID,
                ],
            ).aggregate(tot=Sum("balance_due"))["tot"]
            or DECIMAL_ZERO
        )

        assert gl_ar_balance == customer_subledger_total
        assert customer_subledger_total == invoice_unpaid_total

        # 2. General Ledger Trial Balance Invariant
        tb = get_trial_balance(organization_id=org.pk)
        assert tb["is_balanced"] is True
        assert tb["total_debit"] == tb["total_credit"]


@pytest.fixture
def synthetic_recon_org(db: None) -> dict[str, Any]:
    """Isolated tenant environment configured for lifecycle transaction invariant testing."""
    owner = User.objects.create_user(email="controller@synthetic.test", password="Password123!")
    org = provision_organization(
        name="Synthetic Controls Corp",
        slug="synthetic-controls",
        owner=owner,
        plan="growth",
        base_currency="USD",
        branch_name="Main Depot",
        branch_code="DEP-01",
        warehouse_name="Depot Warehouse",
        warehouse_code="WH-DEP01",
    )
    with tenant_context(org):
        seed_chart_of_accounts(organization=org)
        seed_fiscal_calendar(organization=org, year=timezone.now().year)

        branch = Branch.all_tenants.get(organization=org, code="DEP-01")
        warehouse = Warehouse.all_tenants.get(organization=org, code="WH-DEP01")

        unit = Unit.all_tenants.create(organization=org, name="Piece", code="PCS")
        tax_code = TaxCode.all_tenants.create(
            organization=org, code="VAT10", name="VAT 10%", rate=Decimal("10.00")
        )
        cat = Category.all_tenants.create(organization=org, name="Industrial", slug="ind")

        product = Product.all_tenants.create(
            organization=org,
            name="Precision Sensor",
            sku="SENS-01",
            type=ProductType.STOCK,
            selling_price=Decimal("200.0000"),
            cost_price=Decimal("100.0000"),
            unit=unit,
            tax_code=tax_code,
            category=cat,
        )

        supplier = purchasing_services.create_supplier(
            organization=org,
            code="SUP-SYNTH-01",
            name="Synthetic Sensor Labs",
            contact_person="Sam Sensor",
            email="sam@sensorlabs.test",
            currency="USD",
            actor=owner,
        )

        customer = customers_services.create_customer(
            organization=org,
            name="Automated Systems Ltd",
            email="ap@autosystems.test",
            currency="USD",
            credit_limit=Decimal("50000.0000"),
            actor=owner,
        )

        # Capital injection $20,000 to fund bank account
        post_entry(
            organization=org,
            date=timezone.now().date(),
            memo="Initial capital injection",
            lines=[
                Dr("1020", Decimal("20000.0000")),
                Cr("3000", Decimal("20000.0000")),
            ],
            actor=owner,
        )

        return {
            "org": org,
            "owner": owner,
            "branch": branch,
            "warehouse": warehouse,
            "product": product,
            "supplier": supplier,
            "customer": customer,
        }


@pytest.mark.django_db(transaction=True)
def test_full_lifecycle_control_account_reconciliation(
    synthetic_recon_org: dict[str, Any],
) -> None:
    """Assert mathematical invariants after interleaved procure-to-pay and order-to-cash transactions."""
    env = synthetic_recon_org
    org: Organization = env["org"]
    owner: User = env["owner"]
    warehouse: Warehouse = env["warehouse"]
    branch: Branch = env["branch"]
    product: Product = env["product"]
    supplier: Supplier = env["supplier"]
    customer: Customer = env["customer"]

    with tenant_context(org):
        ar_acc = resolve_mapped_account(organization_id=org.pk, mapping_key="ar")
        ap_acc = resolve_mapped_account(organization_id=org.pk, mapping_key="ap")
        inv_acc = resolve_mapped_account(organization_id=org.pk, mapping_key="inventory.asset")
        assert ar_acc and ap_acc and inv_acc

        def assert_all_reconciliation_invariants() -> None:
            # AR Subledger == Control 1100
            bal_ar = get_account_balance(organization_id=org.pk, account_id=ar_acc.pk)
            cust_total = (
                Customer.all_tenants.filter(organization=org).aggregate(tot=Sum("current_balance"))["tot"]
                or DECIMAL_ZERO
            )
            inv_due = (
                Invoice.all_tenants.filter(
                    organization=org,
                    status__in=[InvoiceStatus.POSTED, InvoiceStatus.PARTIALLY_PAID],
                ).aggregate(tot=Sum("balance_due"))["tot"]
                or DECIMAL_ZERO
            )
            assert bal_ar == cust_total == inv_due

            # AP Subledger == Control 2000
            bal_ap = get_account_balance(organization_id=org.pk, account_id=ap_acc.pk)
            supp_total = (
                Supplier.all_tenants.filter(organization=org).aggregate(tot=Sum("current_balance"))["tot"]
                or DECIMAL_ZERO
            )
            bill_due = (
                SupplierBill.all_tenants.filter(
                    organization=org,
                    status__in=[SupplierBillStatus.POSTED, SupplierBillStatus.PARTIALLY_PAID],
                ).aggregate(tot=Sum("balance_due"))["tot"]
                or DECIMAL_ZERO
            )
            assert bal_ap == supp_total == bill_due

            # Inventory Subledger == Control 1200
            bal_inv = get_account_balance(organization_id=org.pk, account_id=inv_acc.pk)
            stk_tot = sum(
                (sl.on_hand * sl.product.cost_price).quantize(FOUR_PLACES)
                for sl in StockLevel.all_tenants.filter(organization=org).select_related("product")
            )
            assert bal_inv == stk_tot

            # GL Trial Balance
            tb = get_trial_balance(organization_id=org.pk)
            assert tb["is_balanced"] is True
            assert tb["total_debit"] == tb["total_credit"]

        # Initial clean state: AR=0, AP=0, Inventory=0
        assert_all_reconciliation_invariants()

        # Step 1: Purchasing: PO for 20 units -> Receipt -> Post Bill
        po = purchasing_services.create_purchase_order(
            organization=org,
            supplier=supplier,
            warehouse=warehouse,
            lines=[
                {
                    "product": product,
                    "quantity": Decimal("20.0000"),
                    "unit_price": product.cost_price,
                    "tax_rate": Decimal("10.00"),
                }
            ],
            actor=owner,
        )
        purchasing_services.approve_purchase_order(organization=org, purchase_order=po, actor=owner)
        gr = purchasing_services.create_goods_receipt(
            organization=org,
            supplier=supplier,
            warehouse=warehouse,
            purchase_order=po,
            lines=[
                {
                    "product": product,
                    "quantity": Decimal("20.0000"),
                    "unit_cost": product.cost_price,
                    "po_line": po.lines.first(),
                }
            ],
            actor=owner,
        )
        purchasing_services.receive_goods_receipt(organization=org, goods_receipt=gr, actor=owner)
        bill = purchasing_services.create_supplier_bill(
            organization=org,
            supplier=supplier,
            purchase_order=po,
            goods_receipt=gr,
            due_date=timezone.now().date() + datetime.timedelta(days=30),
            lines=[
                {
                    "product": product,
                    "quantity": Decimal("20.0000"),
                    "unit_price": product.cost_price,
                    "tax_rate": Decimal("10.00"),
                }
            ],
            actor=owner,
        )
        bill = purchasing_services.post_supplier_bill(organization=org, bill=bill, actor=owner)
        assert_all_reconciliation_invariants()

        # Step 2: Pay supplier partial $1000
        purchasing_services.record_supplier_payment(
            organization=org,
            supplier=supplier,
            amount=Decimal("1000.0000"),
            payment_method=SupplierPaymentMethod.BANK_TRANSFER,
            allocations=[{"bill_id": bill.pk, "amount": Decimal("1000.0000")}],
            actor=owner,
        )
        assert_all_reconciliation_invariants()

        # Step 3: Sales: Order for 8 units -> Post Invoice
        order = sales_services.create_sales_order(
            organization=org,
            customer=customer,
            branch=branch,
            warehouse=warehouse,
            lines=[
                {
                    "product": product,
                    "quantity": Decimal("8.0000"),
                    "unit_price": product.selling_price,
                    "tax_rate": Decimal("10.00"),
                }
            ],
            actor=owner,
        )
        sales_services.confirm_sales_order(organization=org, order=order, actor=owner)
        inv = sales_services.convert_order_to_invoice(organization=org, order=order, actor=owner)
        inv = sales_services.post_invoice(organization=org, invoice=inv, actor=owner)
        assert_all_reconciliation_invariants()

        # Step 4: Customer pays partial $500
        sales_services.receive_payment(
            organization=org,
            customer=customer,
            amount=Decimal("500.0000"),
            payment_method=PaymentMethod.BANK_TRANSFER,
            allocations=[{"invoice_id": inv.pk, "amount": Decimal("500.0000")}],
            actor=owner,
        )
        assert_all_reconciliation_invariants()

        # Step 5: Full remaining settlement of customer invoice
        inv.refresh_from_db()
        remaining_inv = inv.balance_due
        sales_services.receive_payment(
            organization=org,
            customer=customer,
            amount=remaining_inv,
            payment_method=PaymentMethod.BANK_TRANSFER,
            allocations=[{"invoice_id": inv.pk, "amount": remaining_inv}],
            actor=owner,
        )
        assert_all_reconciliation_invariants()
        assert get_account_balance(organization_id=org.pk, account_id=ar_acc.pk) == DECIMAL_ZERO

        # Step 6: Full remaining settlement of supplier bill
        bill.refresh_from_db()
        remaining_bill = bill.balance_due
        purchasing_services.record_supplier_payment(
            organization=org,
            supplier=supplier,
            amount=remaining_bill,
            payment_method=SupplierPaymentMethod.BANK_TRANSFER,
            allocations=[{"bill_id": bill.pk, "amount": remaining_bill}],
            actor=owner,
        )
        assert_all_reconciliation_invariants()
        assert get_account_balance(organization_id=org.pk, account_id=ap_acc.pk) == DECIMAL_ZERO


@pytest.mark.django_db(transaction=True)
@settings(
    max_examples=10,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    buy_qty=st.integers(min_value=5, max_value=50),
    sell_qty=st.integers(min_value=1, max_value=4),
    pay_supp_pct=st.integers(min_value=10, max_value=90),
    cust_pay_pct=st.integers(min_value=10, max_value=90),
)
def test_hypothesis_control_account_reconciliation_property(
    synthetic_recon_org: dict[str, Any],
    buy_qty: int,
    sell_qty: int,
    pay_supp_pct: int,
    cust_pay_pct: int,
) -> None:
    """Property: Any valid purchasing & sales stream strictly preserves reconciliation invariants."""
    env = synthetic_recon_org
    org: Organization = env["org"]
    owner: User = env["owner"]
    warehouse: Warehouse = env["warehouse"]
    branch: Branch = env["branch"]
    product: Product = env["product"]
    supplier: Supplier = env["supplier"]
    customer: Customer = env["customer"]

    with tenant_context(org):
        ar_acc = resolve_mapped_account(organization_id=org.pk, mapping_key="ar")
        ap_acc = resolve_mapped_account(organization_id=org.pk, mapping_key="ap")
        inv_acc = resolve_mapped_account(organization_id=org.pk, mapping_key="inventory.asset")
        assert ar_acc and ap_acc and inv_acc

        # 1. Purchase & Post Bill
        po = purchasing_services.create_purchase_order(
            organization=org,
            supplier=supplier,
            warehouse=warehouse,
            lines=[
                {
                    "product": product,
                    "quantity": Decimal(buy_qty),
                    "unit_price": product.cost_price,
                    "tax_rate": Decimal("0.00"),
                }
            ],
            actor=owner,
        )
        purchasing_services.approve_purchase_order(organization=org, purchase_order=po, actor=owner)
        gr = purchasing_services.create_goods_receipt(
            organization=org,
            supplier=supplier,
            warehouse=warehouse,
            purchase_order=po,
            lines=[
                {
                    "product": product,
                    "quantity": Decimal(buy_qty),
                    "unit_cost": product.cost_price,
                    "po_line": po.lines.first(),
                }
            ],
            actor=owner,
        )
        purchasing_services.receive_goods_receipt(organization=org, goods_receipt=gr, actor=owner)
        bill = purchasing_services.create_supplier_bill(
            organization=org,
            supplier=supplier,
            purchase_order=po,
            goods_receipt=gr,
            due_date=timezone.now().date() + datetime.timedelta(days=30),
            lines=[
                {
                    "product": product,
                    "quantity": Decimal(buy_qty),
                    "unit_price": product.cost_price,
                    "tax_rate": Decimal("0.00"),
                }
            ],
            actor=owner,
        )
        bill = purchasing_services.post_supplier_bill(organization=org, bill=bill, actor=owner)

        # 2. Partial supplier payment
        supp_pay_amt = (bill.total_amount * Decimal(pay_supp_pct) / Decimal("100")).quantize(FOUR_PLACES)
        purchasing_services.record_supplier_payment(
            organization=org,
            supplier=supplier,
            amount=supp_pay_amt,
            payment_method=SupplierPaymentMethod.BANK_TRANSFER,
            allocations=[{"bill_id": bill.pk, "amount": supp_pay_amt}],
            actor=owner,
        )

        # 3. Sale & Post Invoice
        order = sales_services.create_sales_order(
            organization=org,
            customer=customer,
            branch=branch,
            warehouse=warehouse,
            lines=[
                {
                    "product": product,
                    "quantity": Decimal(sell_qty),
                    "unit_price": product.selling_price,
                    "tax_rate": Decimal("0.00"),
                }
            ],
            actor=owner,
        )
        sales_services.confirm_sales_order(organization=org, order=order, actor=owner)
        inv = sales_services.convert_order_to_invoice(organization=org, order=order, actor=owner)
        inv = sales_services.post_invoice(organization=org, invoice=inv, actor=owner)

        # 4. Partial customer payment
        cust_pay_amt = (inv.grand_total * Decimal(cust_pay_pct) / Decimal("100")).quantize(FOUR_PLACES)
        sales_services.receive_payment(
            organization=org,
            customer=customer,
            amount=cust_pay_amt,
            payment_method=PaymentMethod.BANK_TRANSFER,
            allocations=[{"invoice_id": inv.pk, "amount": cust_pay_amt}],
            actor=owner,
        )

        # Invariant Assertions:
        bal_ar = get_account_balance(organization_id=org.pk, account_id=ar_acc.pk)
        cust_bal = (
            Customer.all_tenants.filter(organization=org).aggregate(tot=Sum("current_balance"))["tot"]
            or DECIMAL_ZERO
        )
        inv_bal = (
            Invoice.all_tenants.filter(
                organization=org,
                status__in=[InvoiceStatus.POSTED, InvoiceStatus.PARTIALLY_PAID],
            ).aggregate(tot=Sum("balance_due"))["tot"]
            or DECIMAL_ZERO
        )
        assert bal_ar == cust_bal == inv_bal

        bal_ap = get_account_balance(organization_id=org.pk, account_id=ap_acc.pk)
        supp_bal = (
            Supplier.all_tenants.filter(organization=org).aggregate(tot=Sum("current_balance"))["tot"]
            or DECIMAL_ZERO
        )
        bill_bal = (
            SupplierBill.all_tenants.filter(
                organization=org,
                status__in=[SupplierBillStatus.POSTED, SupplierBillStatus.PARTIALLY_PAID],
            ).aggregate(tot=Sum("balance_due"))["tot"]
            or DECIMAL_ZERO
        )
        assert bal_ap == supp_bal == bill_bal

        bal_inv = get_account_balance(organization_id=org.pk, account_id=inv_acc.pk)
        stock_tot = sum(
            (sl.on_hand * sl.product.cost_price).quantize(FOUR_PLACES)
            for sl in StockLevel.all_tenants.filter(organization=org).select_related("product")
        )
        assert bal_inv == stock_tot

        tb = get_trial_balance(organization_id=org.pk)
        assert tb["is_balanced"] is True
        assert tb["total_debit"] == tb["total_credit"]
