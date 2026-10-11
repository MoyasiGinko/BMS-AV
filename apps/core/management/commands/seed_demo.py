"""Management command to seed realistic demo organizations for demonstration and testing."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounting import services as accounting_services
from apps.accounting.models import Account, BankAccount
from apps.accounting.services import Cr, Dr, create_expense, create_expense_category, post_entry, post_expense
from apps.accounts.models import User
from apps.billing.services import seed_default_plans
from apps.catalog.models import Category, Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.customers import services as customers_services
from apps.customers.models import Customer
from apps.inventory import services as inventory_services
from apps.pos import services as pos_services
from apps.pos.models import POSRegister
from apps.purchasing import services as purchasing_services
from apps.purchasing.models import Supplier, SupplierPaymentMethod
from apps.sales import services as sales_services
from apps.sales.models import PaymentMethod, RecurringFrequency
from apps.tenancy.models import Branch, Membership, Organization, Role, TaxCode, Warehouse
from apps.tenancy.services import provision_organization


class Command(BaseCommand):
    help = "Seeds realistic demo organizations (Small Shop, Growing Company, Full ERP) with demo12345 users."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--target",
            type=str,
            default="all",
            help="Target organization to seed: 'small_shop', 'growing_company', or 'all' (default: all)",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing demo organization before seeding if it already exists.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        target = options.get("target", "all").lower()
        reset = bool(options.get("reset", False))

        self.stdout.write("Initializing demo billing plans...")
        seed_default_plans()

        if target in ("all", "small_shop", "small-shop"):
            self.stdout.write("Seeding 'Small Shop' organization (Artisan Bakery & Cafe)...")
            org = seed_small_shop(reset=reset, stdout_write=self.stdout.write)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully seeded '{org.name}' ({org.slug})! Ready for POS and invoicing."
                )
            )

        if target in ("all", "growing_company", "growing-company"):
            self.stdout.write("Seeding 'Growing Company' organization (Apex Industrial Wholesale)...")
            org_growth = seed_growing_company(reset=reset, stdout_write=self.stdout.write)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully seeded '{org_growth.name}' ({org_growth.slug})! "
                    "Ready for multi-warehouse purchasing, sales, and accounting."
                )
            )


def _create_user(email: str, name: str) -> User:
    u, _ = User.objects.get_or_create(
        email=email,
        defaults={"name": name, "is_active": True},
    )
    u.set_password("demo12345")
    u.save()
    return u


def _seed_staff_users() -> tuple[User, User, User, User]:
    owner = _create_user("owner@artisanbakery.com", "Alice Baker")
    cashier = _create_user("cashier@artisanbakery.com", "Charlie Cashier")
    manager = _create_user("manager@artisanbakery.com", "Mary Manager")
    accountant = _create_user("accountant@artisanbakery.com", "Arthur Ledger")
    return owner, cashier, manager, accountant


def _assign_roles(
    org: Organization,
    cashier: User,
    manager: User,
    accountant: User,
) -> None:
    roles = Role.all_tenants.filter(organization=org)
    role_cashier = roles.filter(name="Cashier").first()
    role_manager = roles.filter(name="Manager").first()
    role_accountant = roles.filter(name="Accountant").first()

    Membership.all_tenants.get_or_create(
        organization=org,
        user=cashier,
        defaults={"role": role_cashier, "status": Membership.STATUS_ACTIVE},
    )
    Membership.all_tenants.get_or_create(
        organization=org,
        user=manager,
        defaults={"role": role_manager, "status": Membership.STATUS_ACTIVE},
    )
    Membership.all_tenants.get_or_create(
        organization=org,
        user=accountant,
        defaults={"role": role_accountant, "status": Membership.STATUS_ACTIVE},
    )


def _seed_catalog_and_inventory(
    org: Organization,
    warehouse: Warehouse,
    owner: User,
) -> dict[str, Product]:
    unit_pcs, _ = Unit.all_tenants.get_or_create(organization=org, code="pcs", defaults={"name": "Piece"})
    unit_cup, _ = Unit.all_tenants.get_or_create(organization=org, code="cup", defaults={"name": "Cup"})

    tax_vat10 = TaxCode.all_tenants.filter(organization=org, code="VAT10").first()
    if tax_vat10 is None:
        tax_vat10 = TaxCode.all_tenants.create(
            organization=org, code="VAT10", name="VAT 10%", rate=Decimal("10.00")
        )

    tax_zero, _ = TaxCode.all_tenants.get_or_create(
        organization=org, code="ZERO", defaults={"name": "Zero Rated (0%)", "rate": Decimal("0.00")}
    )

    cat_pastries, _ = Category.all_tenants.get_or_create(
        organization=org, slug="pastries", defaults={"name": "Pastries & Baked Goods", "sort_order": 1}
    )
    cat_hot_bev, _ = Category.all_tenants.get_or_create(
        organization=org, slug="hot-drinks", defaults={"name": "Hot Beverages & Coffee", "sort_order": 2}
    )
    cat_cold_bev, _ = Category.all_tenants.get_or_create(
        organization=org, slug="cold-drinks", defaults={"name": "Cold Drinks", "sort_order": 3}
    )
    cat_retail, _ = Category.all_tenants.get_or_create(
        organization=org, slug="merchandise", defaults={"name": "Packaged Goods & Mugs", "sort_order": 4}
    )

    products_spec = [
        (
            "Butter Croissant",
            "PAST-01",
            Decimal("3.5000"),
            Decimal("1.2000"),
            unit_pcs,
            cat_pastries,
            tax_vat10,
            Decimal("100.0000"),
        ),
        (
            "Almond Croissant",
            "PAST-02",
            Decimal("4.5000"),
            Decimal("1.6000"),
            unit_pcs,
            cat_pastries,
            tax_vat10,
            Decimal("80.0000"),
        ),
        (
            "Artisan Sourdough Loaf",
            "BREAD-01",
            Decimal("7.0000"),
            Decimal("2.5000"),
            unit_pcs,
            cat_pastries,
            tax_zero,
            Decimal("50.0000"),
        ),
        (
            "Cinnamon Roll",
            "PAST-03",
            Decimal("4.0000"),
            Decimal("1.4000"),
            unit_pcs,
            cat_pastries,
            tax_vat10,
            Decimal("60.0000"),
        ),
        (
            "Espresso Double",
            "COF-01",
            Decimal("3.0000"),
            Decimal("0.5000"),
            unit_cup,
            cat_hot_bev,
            tax_vat10,
            Decimal("300.0000"),
        ),
        (
            "Cafe Latte",
            "COF-02",
            Decimal("4.5000"),
            Decimal("0.9000"),
            unit_cup,
            cat_hot_bev,
            tax_vat10,
            Decimal("250.0000"),
        ),
        (
            "Cappuccino",
            "COF-03",
            Decimal("4.5000"),
            Decimal("0.9000"),
            unit_cup,
            cat_hot_bev,
            tax_vat10,
            Decimal("200.0000"),
        ),
        (
            "Cold Brew Iced Coffee",
            "COF-04",
            Decimal("5.0000"),
            Decimal("1.1000"),
            unit_cup,
            cat_cold_bev,
            tax_vat10,
            Decimal("150.0000"),
        ),
        (
            "House Blend Beans 500g",
            "RET-01",
            Decimal("16.0000"),
            Decimal("8.0000"),
            unit_pcs,
            cat_retail,
            tax_vat10,
            Decimal("50.0000"),
        ),
        (
            "Ceramic Bakery Mug",
            "RET-02",
            Decimal("14.0000"),
            Decimal("5.0000"),
            unit_pcs,
            cat_retail,
            tax_vat10,
            Decimal("40.0000"),
        ),
    ]

    products_map: dict[str, Product] = {}
    for name, sku, sell_p, cost_p, uom, cat, tax, init_qty in products_spec:
        prod, _ = Product.all_tenants.get_or_create(
            organization=org,
            sku=sku,
            defaults={
                "name": name,
                "type": ProductType.STOCK,
                "selling_price": sell_p,
                "cost_price": cost_p,
                "unit": uom,
                "category": cat,
                "tax_code": tax,
            },
        )
        products_map[sku] = prod

        inventory_services.receive_stock(
            organization=org,
            warehouse=warehouse,
            product=prod,
            quantity=init_qty,
            unit_cost=cost_p,
            reference_type="initial_inventory",
            reference_id="SEED-INIT",
            notes=f"Initial stock for {name}",
            actor=owner,
        )

    return products_map


def _seed_customers(org: Organization, owner: User) -> tuple[Customer, Customer]:
    cust_acme = customers_services.create_customer(
        organization=org,
        name="Green Valley Catering",
        email="catering@greenvalley.com",
        phone="+1-555-0199",
        credit_limit=Decimal("5000.0000"),
        payment_terms_days=15,
        actor=owner,
    )
    customers_services.add_customer_address(
        organization=org,
        customer=cust_acme,
        type="billing",
        line1="100 Innovation Way, Suite 400",
        city="Metropolis",
        postal_code="94107",
        country="USA",
        is_default=True,
    )

    cust_metro = customers_services.create_customer(
        organization=org,
        name="Metropolitan Co-working",
        email="frontdesk@metrocowork.com",
        phone="+1-555-0244",
        credit_limit=Decimal("10000.0000"),
        payment_terms_days=30,
        actor=owner,
    )

    customers_services.create_customer(
        organization=org,
        name="Downtown Events Collective",
        email="hello@downtownevents.org",
        phone="+1-555-0311",
        credit_limit=Decimal("8000.0000"),
        payment_terms_days=14,
        actor=owner,
    )

    return cust_acme, cust_metro


def _seed_pos_operations(
    *,
    org: Organization,
    branch: Branch,
    warehouse: Warehouse,
    owner: User,
    cashier: User,
    products_map: dict[str, Product],
) -> POSRegister:
    register = pos_services.create_register(
        organization=org,
        name="Front Counter 1",
        code="REG-01",
        branch=branch,
        warehouse=warehouse,
        receipt_header="Artisan Bakery & Cafe\n123 Main Street\nFreshly Baked Every Morning",
        receipt_footer="Thank you for visiting! Follow us @artisanbakery",
        actor=owner,
    )

    shift_1 = pos_services.open_shift(
        organization=org,
        register=register,
        cashier=cashier,
        opening_cash=Decimal("100.0000"),
        notes="Morning Shift 1",
        actor=cashier,
    )

    croissant = products_map["PAST-01"]
    latte = products_map["COF-02"]
    pos_services.checkout_pos_sale(
        organization=org,
        shift=shift_1,
        lines=[
            {
                "product": croissant,
                "quantity": Decimal("2.0000"),
                "unit_price": croissant.selling_price,
                "tax_rate": Decimal("10.00"),
            },
            {
                "product": latte,
                "quantity": Decimal("2.0000"),
                "unit_price": latte.selling_price,
                "tax_rate": Decimal("10.00"),
            },
        ],
        payments=[{"payment_method": "cash", "amount": Decimal("17.6000")}],
        amount_tendered=Decimal("20.0000"),
        notes="Counter order #1",
        actor=cashier,
    )

    sourdough = products_map["BREAD-01"]
    beans = products_map["RET-01"]
    pos_services.checkout_pos_sale(
        organization=org,
        shift=shift_1,
        lines=[
            {
                "product": sourdough,
                "quantity": Decimal("1.0000"),
                "unit_price": sourdough.selling_price,
                "tax_rate": Decimal("0.00"),
            },
            {
                "product": beans,
                "quantity": Decimal("1.0000"),
                "unit_price": beans.selling_price,
                "tax_rate": Decimal("10.00"),
            },
        ],
        payments=[{"payment_method": "card", "amount": Decimal("24.6000")}],
        notes="Card payment counter order #2",
        actor=cashier,
    )

    pos_services.close_shift(
        organization=org,
        shift=shift_1,
        closing_cash_counted=Decimal("117.6000"),
        notes="Cash counted and verified balanced.",
        actor=cashier,
    )

    pos_services.open_shift(
        organization=org,
        register=register,
        cashier=cashier,
        opening_cash=Decimal("120.0000"),
        notes="Current active afternoon shift",
        actor=cashier,
    )

    return register


def _seed_b2b_sales(
    *,
    org: Organization,
    branch: Branch,
    warehouse: Warehouse,
    owner: User,
    manager: User,
    accountant: User,
    products_map: dict[str, Product],
    cust_acme: Customer,
    cust_metro: Customer,
) -> None:
    beans = products_map["RET-01"]
    mug = products_map["RET-02"]
    quote = sales_services.create_quote(
        organization=org,
        customer=cust_acme,
        branch=branch,
        warehouse=warehouse,
        lines=[
            {
                "product": beans,
                "quantity": Decimal("5.0000"),
                "unit_price": beans.selling_price,
                "discount_percent": Decimal("5.00"),
                "tax_rate": Decimal("10.00"),
            },
            {
                "product": mug,
                "quantity": Decimal("4.0000"),
                "unit_price": mug.selling_price,
                "discount_percent": Decimal("0.00"),
                "tax_rate": Decimal("10.00"),
            },
        ],
        notes="Corporate office coffee supply quote",
        actor=owner,
    )
    quote = sales_services.accept_quote(organization=org, quote=quote, actor=owner)
    order = sales_services.convert_quote_to_order(organization=org, quote=quote, actor=owner)
    order = sales_services.confirm_sales_order(organization=org, order=order, actor=owner)
    invoice = sales_services.convert_order_to_invoice(organization=org, order=order, actor=owner)
    invoice = sales_services.post_invoice(organization=org, invoice=invoice, actor=owner)

    sales_services.receive_payment(
        organization=org,
        customer=cust_acme,
        amount=Decimal("100.0000"),
        payment_method=PaymentMethod.BANK_TRANSFER,
        allocations=[{"invoice_id": invoice.pk, "amount": Decimal("100.0000")}],
        reference="WIRE-ACME-001",
        notes="Partial deposit payment received via Wire",
        actor=accountant,
    )

    croissant = products_map["PAST-01"]
    latte = products_map["COF-02"]
    sales_services.create_sales_order(
        organization=org,
        customer=cust_metro,
        branch=branch,
        warehouse=warehouse,
        lines=[
            {
                "product": croissant,
                "quantity": Decimal("20.0000"),
                "unit_price": croissant.selling_price,
                "tax_rate": Decimal("10.00"),
            },
            {
                "product": latte,
                "quantity": Decimal("20.0000"),
                "unit_price": latte.selling_price,
                "tax_rate": Decimal("10.00"),
            },
        ],
        notes="Weekly team breakfast catering order",
        actor=manager,
    )


@transaction.atomic
def seed_small_shop(
    *,
    reset: bool = False,
    stdout_write: Any = None,
) -> Organization:
    """Seed the 'Small Shop' demo organization: Artisan Bakery & Cafe."""
    log = stdout_write or (lambda msg: None)
    slug = "small-shop"

    existing = Organization.objects.filter(slug=slug).first()
    if existing:
        if reset:
            log(f"Resetting existing organization '{slug}'...")
            existing.delete()
        else:
            log(f"Organization '{slug}' already exists. Re-verifying credentials.")
            for email in [
                "owner@artisanbakery.com",
                "cashier@artisanbakery.com",
                "manager@artisanbakery.com",
                "accountant@artisanbakery.com",
            ]:
                u = User.objects.filter(email=email).first()
                if u:
                    u.set_password("demo12345")
                    u.save()
            return existing

    owner, cashier, manager, accountant = _seed_staff_users()

    org = provision_organization(
        name="Artisan Bakery & Cafe",
        slug=slug,
        owner=owner,
        plan="starter",
        base_currency="USD",
        branch_name="Downtown Cafe & Bakery",
        branch_code="DT-01",
        warehouse_name="Downtown Storage",
        warehouse_code="WH-DT01",
    )

    with tenant_context(org):
        _assign_roles(org, cashier, manager, accountant)
        accounting_services.seed_chart_of_accounts(organization=org)
        accounting_services.seed_fiscal_calendar(organization=org, year=timezone.now().year)

        branch = Branch.all_tenants.get(organization=org, code="DT-01")
        warehouse = Warehouse.all_tenants.get(organization=org, code="WH-DT01")

        products_map = _seed_catalog_and_inventory(org, warehouse, owner)
        cust_acme, cust_metro = _seed_customers(org, owner)
        _seed_pos_operations(
            org=org,
            branch=branch,
            warehouse=warehouse,
            owner=owner,
            cashier=cashier,
            products_map=products_map,
        )
        _seed_b2b_sales(
            org=org,
            branch=branch,
            warehouse=warehouse,
            owner=owner,
            manager=manager,
            accountant=accountant,
            products_map=products_map,
            cust_acme=cust_acme,
            cust_metro=cust_metro,
        )

    return org


def _seed_growing_company_staff() -> dict[str, User]:
    return {
        "owner": _create_user("owner@apexwholesale.com", "Alex Vance"),
        "sales": _create_user("sales@apexwholesale.com", "Samantha Sales"),
        "buyer": _create_user("buyer@apexwholesale.com", "Brian Buyer"),
        "accountant": _create_user("accountant@apexwholesale.com", "Abigail Ledger"),
        "warehouse": _create_user("warehouse@apexwholesale.com", "Walter Stock"),
    }


def _seed_growing_company_roles(org: Organization, users: dict[str, User]) -> None:
    roles = Role.all_tenants.filter(organization=org)
    role_manager = roles.filter(name="Manager").first()
    role_accountant = roles.filter(name="Accountant").first()

    Membership.all_tenants.get_or_create(
        organization=org,
        user=users["sales"],
        defaults={"role": role_manager, "status": Membership.STATUS_ACTIVE},
    )
    Membership.all_tenants.get_or_create(
        organization=org,
        user=users["buyer"],
        defaults={"role": role_manager, "status": Membership.STATUS_ACTIVE},
    )
    Membership.all_tenants.get_or_create(
        organization=org,
        user=users["warehouse"],
        defaults={"role": role_manager, "status": Membership.STATUS_ACTIVE},
    )
    Membership.all_tenants.get_or_create(
        organization=org,
        user=users["accountant"],
        defaults={"role": role_accountant, "status": Membership.STATUS_ACTIVE},
    )


def _seed_growing_company_catalog(org: Organization) -> dict[str, Product]:
    unit_pcs, _ = Unit.all_tenants.get_or_create(organization=org, code="pcs", defaults={"name": "Piece"})
    unit_box, _ = Unit.all_tenants.get_or_create(
        organization=org, code="box", defaults={"name": "Box (Pack)"}
    )
    unit_roll, _ = Unit.all_tenants.get_or_create(organization=org, code="roll", defaults={"name": "Roll"})

    tax_vat10 = TaxCode.all_tenants.filter(organization=org, code="VAT10").first()
    if tax_vat10 is None:
        tax_vat10 = TaxCode.all_tenants.create(
            organization=org, code="VAT10", name="VAT 10%", rate=Decimal("10.00")
        )

    cat_power, _ = Category.all_tenants.get_or_create(
        organization=org,
        slug="power-equip",
        defaults={"name": "Power Equipment & Machinery", "sort_order": 1},
    )
    cat_safety, _ = Category.all_tenants.get_or_create(
        organization=org,
        slug="safety-gear",
        defaults={"name": "Personal Protective Equipment", "sort_order": 2},
    )
    cat_pack, _ = Category.all_tenants.get_or_create(
        organization=org,
        slug="packaging",
        defaults={"name": "Industrial Packaging Supplies", "sort_order": 3},
    )

    products_spec = [
        (
            "Heavy-Duty Drill Press 750W",
            "EQUIP-01",
            Decimal("599.0000"),
            Decimal("350.0000"),
            unit_pcs,
            cat_power,
            tax_vat10,
        ),
        (
            "Hydraulic Pallet Jack 2500kg",
            "EQUIP-02",
            Decimal("389.0000"),
            Decimal("220.0000"),
            unit_pcs,
            cat_power,
            tax_vat10,
        ),
        (
            "Pro Safety Helmet & Visor",
            "SAFE-01",
            Decimal("55.0000"),
            Decimal("25.0000"),
            unit_pcs,
            cat_safety,
            tax_vat10,
        ),
        (
            "Hi-Vis Work Vest Class 2",
            "SAFE-02",
            Decimal("28.0000"),
            Decimal("12.0000"),
            unit_pcs,
            cat_safety,
            tax_vat10,
        ),
        (
            "Heavy Duty Packing Tape Box",
            "PACK-01",
            Decimal("95.0000"),
            Decimal("45.0000"),
            unit_box,
            cat_pack,
            tax_vat10,
        ),
        (
            "Stretch Film Heavy Pallet Wrap",
            "PACK-02",
            Decimal("38.0000"),
            Decimal("18.0000"),
            unit_roll,
            cat_pack,
            tax_vat10,
        ),
    ]

    prod_map: dict[str, Product] = {}
    for name, sku, sell_p, cost_p, uom, cat, tax in products_spec:
        prod, _ = Product.all_tenants.get_or_create(
            organization=org,
            sku=sku,
            defaults={
                "name": name,
                "type": ProductType.STOCK,
                "selling_price": sell_p,
                "cost_price": cost_p,
                "unit": uom,
                "category": cat,
                "tax_code": tax,
            },
        )
        prod_map[sku] = prod

    return prod_map


def _seed_growing_company_purchasing(
    *,
    org: Organization,
    wh_hub: Warehouse,
    wh_metro: Warehouse,
    buyer: User,
    accountant: User,
    products: dict[str, Product],
) -> dict[str, Supplier]:
    s_titan = purchasing_services.create_supplier(
        organization=org,
        code="SUP-0001",
        name="Titan Machinery Works",
        contact_person="Thomas Titan",
        email="orders@titanmachinery.com",
        payment_terms_days=30,
        currency="USD",
        actor=buyer,
    )
    s_safe = purchasing_services.create_supplier(
        organization=org,
        code="SUP-0002",
        name="SafeGuard Protective Equipment",
        contact_person="Sarah Guard",
        email="sales@safeguardequip.com",
        payment_terms_days=30,
        currency="USD",
        actor=buyer,
    )
    s_pack = purchasing_services.create_supplier(
        organization=org,
        code="SUP-0003",
        name="Global Pack & Freight Logistics",
        contact_person="Gary Pack",
        email="dispatch@globalpack.com",
        payment_terms_days=15,
        currency="USD",
        actor=buyer,
    )

    p_drill = products["EQUIP-01"]
    p_jack = products["EQUIP-02"]
    p_helm = products["SAFE-01"]
    p_vest = products["SAFE-02"]
    p_tape = products["PACK-01"]
    p_wrap = products["PACK-02"]

    # PO 1: Titan Machinery -> WH Hub
    po1 = purchasing_services.create_purchase_order(
        organization=org,
        supplier=s_titan,
        warehouse=wh_hub,
        currency="USD",
        lines=[
            {
                "product": p_drill,
                "quantity": Decimal("10.0000"),
                "unit_price": p_drill.cost_price,
                "tax_rate": Decimal("10.00"),
            },
            {
                "product": p_jack,
                "quantity": Decimal("10.0000"),
                "unit_price": p_jack.cost_price,
                "tax_rate": Decimal("10.00"),
            },
        ],
        notes="Q2 Heavy Machinery Stock Order",
        actor=buyer,
    )
    po1 = purchasing_services.approve_purchase_order(organization=org, purchase_order=po1, actor=buyer)

    receipt1 = purchasing_services.create_goods_receipt(
        organization=org,
        supplier=s_titan,
        warehouse=wh_hub,
        purchase_order=po1,
        lines=[
            {
                "product": p_drill,
                "quantity": Decimal("10.0000"),
                "unit_cost": p_drill.cost_price,
                "po_line": po1.lines.filter(product=p_drill).first(),
            },
            {
                "product": p_jack,
                "quantity": Decimal("10.0000"),
                "unit_cost": p_jack.cost_price,
                "po_line": po1.lines.filter(product=p_jack).first(),
            },
        ],
        notes="Delivered in full by Titan Freight",
        actor=buyer,
    )
    purchasing_services.receive_goods_receipt(organization=org, goods_receipt=receipt1, actor=buyer)

    bill1 = purchasing_services.create_supplier_bill(
        organization=org,
        supplier=s_titan,
        purchase_order=po1,
        goods_receipt=receipt1,
        due_date=timezone.now().date() + datetime.timedelta(days=30),
        lines=[
            {
                "product": p_drill,
                "quantity": Decimal("10.0000"),
                "unit_price": p_drill.cost_price,
                "tax_rate": Decimal("10.00"),
            },
            {
                "product": p_jack,
                "quantity": Decimal("10.0000"),
                "unit_price": p_jack.cost_price,
                "tax_rate": Decimal("10.00"),
            },
        ],
        notes="Titan Invoice #TITAN-9021",
        actor=accountant,
    )
    bill1 = purchasing_services.post_supplier_bill(organization=org, bill=bill1, actor=accountant)

    purchasing_services.record_supplier_payment(
        organization=org,
        supplier=s_titan,
        amount=Decimal("3000.0000"),
        payment_method=SupplierPaymentMethod.BANK_TRANSFER,
        allocations=[{"bill_id": bill1.pk, "amount": Decimal("3000.0000")}],
        reference="WIRE-TITAN-01",
        notes="Deposit payment against bill 1",
        actor=accountant,
    )

    # PO 2: SafeGuard -> WH Metro
    po2 = purchasing_services.create_purchase_order(
        organization=org,
        supplier=s_safe,
        warehouse=wh_metro,
        currency="USD",
        lines=[
            {
                "product": p_helm,
                "quantity": Decimal("40.0000"),
                "unit_price": p_helm.cost_price,
                "tax_rate": Decimal("10.00"),
            },
            {
                "product": p_vest,
                "quantity": Decimal("100.0000"),
                "unit_price": p_vest.cost_price,
                "tax_rate": Decimal("10.00"),
            },
        ],
        notes="PPE Stock for Metro Fulfillment Depot",
        actor=buyer,
    )
    po2 = purchasing_services.approve_purchase_order(organization=org, purchase_order=po2, actor=buyer)

    receipt2 = purchasing_services.create_goods_receipt(
        organization=org,
        supplier=s_safe,
        warehouse=wh_metro,
        purchase_order=po2,
        lines=[
            {
                "product": p_helm,
                "quantity": Decimal("40.0000"),
                "unit_cost": p_helm.cost_price,
                "po_line": po2.lines.filter(product=p_helm).first(),
            },
            {
                "product": p_vest,
                "quantity": Decimal("100.0000"),
                "unit_cost": p_vest.cost_price,
                "po_line": po2.lines.filter(product=p_vest).first(),
            },
        ],
        notes="Metro PPE batch delivery",
        actor=buyer,
    )
    purchasing_services.receive_goods_receipt(organization=org, goods_receipt=receipt2, actor=buyer)

    bill2 = purchasing_services.create_supplier_bill(
        organization=org,
        supplier=s_safe,
        purchase_order=po2,
        goods_receipt=receipt2,
        due_date=timezone.now().date() + datetime.timedelta(days=30),
        lines=[
            {
                "product": p_helm,
                "quantity": Decimal("40.0000"),
                "unit_price": p_helm.cost_price,
                "tax_rate": Decimal("10.00"),
            },
            {
                "product": p_vest,
                "quantity": Decimal("100.0000"),
                "unit_price": p_vest.cost_price,
                "tax_rate": Decimal("10.00"),
            },
        ],
        notes="SafeGuard Invoice #SG-4412",
        actor=accountant,
    )
    bill2 = purchasing_services.post_supplier_bill(organization=org, bill=bill2, actor=accountant)

    purchasing_services.record_supplier_payment(
        organization=org,
        supplier=s_safe,
        amount=bill2.total_amount,
        payment_method=SupplierPaymentMethod.BANK_TRANSFER,
        allocations=[{"bill_id": bill2.pk, "amount": bill2.total_amount}],
        reference="WIRE-SAFEGUARD-01",
        notes="Full bill settlement via Wire",
        actor=accountant,
    )

    # PO 3: Global Pack -> WH Hub (Unpaid bill)
    po3 = purchasing_services.create_purchase_order(
        organization=org,
        supplier=s_pack,
        warehouse=wh_hub,
        currency="USD",
        lines=[
            {
                "product": p_tape,
                "quantity": Decimal("30.0000"),
                "unit_price": p_tape.cost_price,
                "tax_rate": Decimal("10.00"),
            },
            {
                "product": p_wrap,
                "quantity": Decimal("60.0000"),
                "unit_price": p_wrap.cost_price,
                "tax_rate": Decimal("10.00"),
            },
        ],
        notes="Packaging supplies replenish",
        actor=buyer,
    )
    po3 = purchasing_services.approve_purchase_order(organization=org, purchase_order=po3, actor=buyer)

    receipt3 = purchasing_services.create_goods_receipt(
        organization=org,
        supplier=s_pack,
        warehouse=wh_hub,
        purchase_order=po3,
        lines=[
            {
                "product": p_tape,
                "quantity": Decimal("30.0000"),
                "unit_cost": p_tape.cost_price,
                "po_line": po3.lines.filter(product=p_tape).first(),
            },
            {
                "product": p_wrap,
                "quantity": Decimal("60.0000"),
                "unit_cost": p_wrap.cost_price,
                "po_line": po3.lines.filter(product=p_wrap).first(),
            },
        ],
        notes="Pallet packaging arrival",
        actor=buyer,
    )
    purchasing_services.receive_goods_receipt(organization=org, goods_receipt=receipt3, actor=buyer)

    bill3 = purchasing_services.create_supplier_bill(
        organization=org,
        supplier=s_pack,
        purchase_order=po3,
        goods_receipt=receipt3,
        due_date=timezone.now().date() + datetime.timedelta(days=15),
        lines=[
            {
                "product": p_tape,
                "quantity": Decimal("30.0000"),
                "unit_price": p_tape.cost_price,
                "tax_rate": Decimal("10.00"),
            },
            {
                "product": p_wrap,
                "quantity": Decimal("60.0000"),
                "unit_price": p_wrap.cost_price,
                "tax_rate": Decimal("10.00"),
            },
        ],
        notes="Global Pack Invoice #GP-8891",
        actor=accountant,
    )
    purchasing_services.post_supplier_bill(organization=org, bill=bill3, actor=accountant)

    return {"titan": s_titan, "safe": s_safe, "pack": s_pack}


def _seed_growing_company_sales(
    *,
    org: Organization,
    branch_hub: Branch,
    wh_hub: Warehouse,
    branch_metro: Branch,
    wh_metro: Warehouse,
    owner: User,
    sales_mgr: User,
    accountant: User,
    products: dict[str, Product],
) -> dict[str, Customer]:
    c_conti = customers_services.create_customer(
        organization=org,
        name="Continental Construction Corp",
        email="procurement@continentalconst.com",
        phone="+1-555-0301",
        credit_limit=Decimal("25000.0000"),
        payment_terms_days=30,
        actor=owner,
    )
    c_apex = customers_services.create_customer(
        organization=org,
        name="Apex Regional Contractors",
        email="billing@apexregional.com",
        phone="+1-555-0302",
        credit_limit=Decimal("15000.0000"),
        payment_terms_days=15,
        actor=owner,
    )
    c_nexus = customers_services.create_customer(
        organization=org,
        name="Nexus Logistics Fleet",
        email="ap@nexuslogistics.com",
        phone="+1-555-0303",
        credit_limit=Decimal("30000.0000"),
        payment_terms_days=30,
        actor=owner,
    )

    p_drill = products["EQUIP-01"]
    p_jack = products["EQUIP-02"]
    p_helm = products["SAFE-01"]
    p_vest = products["SAFE-02"]
    p_tape = products["PACK-01"]
    p_wrap = products["PACK-02"]

    # Transfer 10 helmets from WH Metro to WH Hub
    inventory_services.transfer_stock(
        organization=org,
        source_warehouse=wh_metro,
        destination_warehouse=wh_hub,
        lines=[{"product": p_helm, "quantity": Decimal("10.0000")}],
        notes="Internal branch transfer for Continental order",
        actor=owner,
    )

    # Sale 1 to Continental: 2 drills + 10 helmets, partial payment
    q1 = sales_services.create_quote(
        organization=org,
        customer=c_conti,
        branch=branch_hub,
        warehouse=wh_hub,
        lines=[
            {
                "product": p_drill,
                "quantity": Decimal("2.0000"),
                "unit_price": p_drill.selling_price,
                "tax_rate": Decimal("10.00"),
            },
            {
                "product": p_helm,
                "quantity": Decimal("10.0000"),
                "unit_price": p_helm.selling_price,
                "tax_rate": Decimal("10.00"),
            },
        ],
        notes="Equipment & safety package quote",
        actor=sales_mgr,
    )
    q1 = sales_services.accept_quote(organization=org, quote=q1, actor=sales_mgr)
    ord1 = sales_services.convert_quote_to_order(organization=org, quote=q1, actor=sales_mgr)
    ord1 = sales_services.confirm_sales_order(organization=org, order=ord1, actor=sales_mgr)
    inv1 = sales_services.convert_order_to_invoice(organization=org, order=ord1, actor=sales_mgr)
    inv1 = sales_services.post_invoice(organization=org, invoice=inv1, actor=sales_mgr)

    sales_services.receive_payment(
        organization=org,
        customer=c_conti,
        amount=Decimal("1000.0000"),
        payment_method=PaymentMethod.BANK_TRANSFER,
        allocations=[{"invoice_id": inv1.pk, "amount": Decimal("1000.0000")}],
        reference="WIRE-CONTI-01",
        notes="Deposit payment against invoice 1",
        actor=accountant,
    )

    # Sale 2 to Apex Regional: 1 jack + 10 tape boxes, unpaid
    ord2 = sales_services.create_sales_order(
        organization=org,
        customer=c_apex,
        branch=branch_hub,
        warehouse=wh_hub,
        lines=[
            {
                "product": p_jack,
                "quantity": Decimal("1.0000"),
                "unit_price": p_jack.selling_price,
                "tax_rate": Decimal("10.00"),
            },
            {
                "product": p_tape,
                "quantity": Decimal("10.0000"),
                "unit_price": p_tape.selling_price,
                "tax_rate": Decimal("10.00"),
            },
        ],
        notes="Warehouse supplies order",
        actor=sales_mgr,
    )
    ord2 = sales_services.confirm_sales_order(organization=org, order=ord2, actor=sales_mgr)
    inv2 = sales_services.convert_order_to_invoice(organization=org, order=ord2, actor=sales_mgr)
    inv2 = sales_services.post_invoice(organization=org, invoice=inv2, actor=sales_mgr)

    # Transfer 15 wraps from WH Hub to WH Metro
    inventory_services.transfer_stock(
        organization=org,
        source_warehouse=wh_hub,
        destination_warehouse=wh_metro,
        lines=[{"product": p_wrap, "quantity": Decimal("15.0000")}],
        notes="Internal branch transfer for Nexus order",
        actor=owner,
    )

    # Sale 3 to Nexus: from WH Metro, fully paid
    ord3 = sales_services.create_sales_order(
        organization=org,
        customer=c_nexus,
        branch=branch_metro,
        warehouse=wh_metro,
        lines=[
            {
                "product": p_vest,
                "quantity": Decimal("20.0000"),
                "unit_price": p_vest.selling_price,
                "tax_rate": Decimal("10.00"),
            },
            {
                "product": p_wrap,
                "quantity": Decimal("15.0000"),
                "unit_price": p_wrap.selling_price,
                "tax_rate": Decimal("10.00"),
            },
        ],
        notes="Fulfillment packing and vests order",
        actor=sales_mgr,
    )
    ord3 = sales_services.confirm_sales_order(organization=org, order=ord3, actor=sales_mgr)
    inv3 = sales_services.convert_order_to_invoice(organization=org, order=ord3, actor=sales_mgr)
    inv3 = sales_services.post_invoice(organization=org, invoice=inv3, actor=sales_mgr)

    sales_services.receive_payment(
        organization=org,
        customer=c_nexus,
        amount=inv3.grand_total,
        payment_method=PaymentMethod.BANK_TRANSFER,
        allocations=[{"invoice_id": inv3.pk, "amount": inv3.grand_total}],
        reference="ACH-NEXUS-01",
        notes="Full invoice payment via ACH",
        actor=accountant,
    )

    return {"conti": c_conti, "apex": c_apex, "nexus": c_nexus}


def _seed_growing_company_accounting(org: Organization, owner: User, accountant: User) -> None:
    gl_bank = Account.all_tenants.get(organization=org, code="1020")
    gl_rent = Account.all_tenants.get(organization=org, code="6100")
    gl_util = Account.all_tenants.get(organization=org, code="6200")

    bank_acct, _ = BankAccount.objects.get_or_create(
        organization=org,
        account_number="ACCT-98765432",
        defaults={
            "name": "Apex Primary Operating Account",
            "bank_name": "Silicon Valley Commercial Bank",
            "currency": "USD",
            "current_balance": Decimal("50000.0000"),
            "gl_account": gl_bank,
            "is_active": True,
        },
    )

    # 1. Partner equity capital injection: $50,000
    post_entry(
        organization=org,
        date=timezone.now().date(),
        memo="Initial partner equity investment",
        lines=[
            Dr("1020", Decimal("50000.0000")),
            Cr("3000", Decimal("50000.0000")),
        ],
        actor=owner,
    )

    # 2. Operating expenses:
    cat_rent = create_expense_category(
        organization=org,
        name="Rent & Facilities",
        code="RENT",
        gl_account=gl_rent,
        actor=owner,
    )
    exp_rent = create_expense(
        organization=org,
        category=cat_rent,
        paid_from_account=gl_bank,
        bank_account=bank_acct,
        date=timezone.now().date(),
        amount=Decimal("3000.0000"),
        vendor_name="Prologis Commercial Real Estate",
        reference="CHK-1001",
        notes="Central warehouse monthly lease",
        actor=accountant,
    )
    post_expense(organization=org, expense=exp_rent, actor=accountant)

    cat_util = create_expense_category(
        organization=org,
        name="Utilities & Telecom",
        code="UTIL",
        gl_account=gl_util,
        actor=owner,
    )
    exp_util = create_expense(
        organization=org,
        category=cat_util,
        paid_from_account=gl_bank,
        bank_account=bank_acct,
        date=timezone.now().date(),
        amount=Decimal("500.0000"),
        vendor_name="Pacific Power & Light",
        reference="ACH-9921",
        notes="Industrial power and water",
        actor=accountant,
    )
    post_expense(organization=org, expense=exp_util, actor=accountant)


def _seed_growing_company_recurring_and_reminders(
    org: Organization,
    wh_hub: Warehouse,
    owner: User,
    customer: Customer,
    products: dict[str, Product],
) -> None:
    p_tape = products["PACK-01"]
    p_vest = products["SAFE-02"]

    sales_services.create_recurring_profile(
        organization=org,
        title="Monthly Warehouse Safety & Consumables Replenishment",
        customer=customer,
        warehouse=wh_hub,
        frequency=RecurringFrequency.MONTHLY,
        interval=1,
        payment_terms_days=30,
        currency="USD",
        auto_post=True,
        send_email=True,
        lines=[
            {
                "product_id": p_tape.pk,
                "quantity": Decimal("5.0000"),
                "unit_price": p_tape.selling_price,
            },
            {
                "product_id": p_vest.pk,
                "quantity": Decimal("10.0000"),
                "unit_price": p_vest.selling_price,
            },
        ],
        notes="Monthly automated safety and packaging shipment",
        actor=owner,
    )

    sales_services.create_payment_reminder_rule(
        organization=org,
        name="Upcoming Invoice Due in 3 Days",
        timing_days=-3,
        is_active=True,
        subject_template="Reminder: Invoice {{ invoice_number }} due in 3 days",
        body_template=(
            "Dear {{ customer_name }}, your invoice {{ invoice_number }} of "
            "{{ currency }} {{ balance_due }} is due on {{ due_date }}."
        ),
        actor=owner,
    )
    sales_services.create_payment_reminder_rule(
        organization=org,
        name="Invoice Due Today",
        timing_days=0,
        is_active=True,
        subject_template="Notice: Invoice {{ invoice_number }} is due today",
        body_template=(
            "Dear {{ customer_name }}, this is a reminder that invoice {{ invoice_number }} "
            "for {{ currency }} {{ balance_due }} is due today."
        ),
        actor=owner,
    )
    sales_services.create_payment_reminder_rule(
        organization=org,
        name="Overdue Notice - 7 Days",
        timing_days=7,
        is_active=True,
        subject_template="Overdue Notice: Invoice {{ invoice_number }}",
        body_template=(
            "Dear {{ customer_name }}, invoice {{ invoice_number }} with balance "
            "{{ currency }} {{ balance_due }} is 7 days past due."
        ),
        actor=owner,
    )


@transaction.atomic
def seed_growing_company(
    *,
    reset: bool = False,
    stdout_write: Any = None,
) -> Organization:
    """Seed the 'Growing Company' demo organization: Apex Industrial Wholesale."""
    log = stdout_write or (lambda msg: None)
    slug = "growing-company"

    existing = Organization.objects.filter(slug=slug).first()
    if existing:
        if reset:
            log(f"Resetting existing organization '{slug}'...")
            existing.delete()
        else:
            log(f"Organization '{slug}' already exists. Re-verifying credentials.")
            for email in [
                "owner@apexwholesale.com",
                "sales@apexwholesale.com",
                "buyer@apexwholesale.com",
                "accountant@apexwholesale.com",
                "warehouse@apexwholesale.com",
            ]:
                u = User.objects.filter(email=email).first()
                if u:
                    u.set_password("demo12345")
                    u.save()
            return existing

    users = _seed_growing_company_staff()
    owner = users["owner"]

    org = provision_organization(
        name="Apex Industrial Wholesale",
        slug=slug,
        owner=owner,
        plan="growth",
        base_currency="USD",
        branch_name="Central Logistics Hub",
        branch_code="HUB-01",
        warehouse_name="Central Logistics Warehouse",
        warehouse_code="WH-HUB01",
    )

    with tenant_context(org):
        _seed_growing_company_roles(org, users)
        accounting_services.seed_chart_of_accounts(organization=org)
        accounting_services.seed_fiscal_calendar(organization=org, year=timezone.now().year)

        branch_hub = Branch.all_tenants.get(organization=org, code="HUB-01")
        wh_hub = Warehouse.all_tenants.get(organization=org, code="WH-HUB01")

        # Additional Branch & Warehouse
        branch_metro = Branch.all_tenants.create(
            organization=org,
            name="Metro Fulfillment Depot",
            code="MET-02",
            is_headquarters=False,
        )
        wh_metro = Warehouse.all_tenants.create(
            organization=org,
            branch=branch_metro,
            name="Metro Regional Depot",
            code="WH-MET02",
            is_default=False,
        )

        catalog_map = _seed_growing_company_catalog(org)
        _seed_growing_company_purchasing(
            org=org,
            wh_hub=wh_hub,
            wh_metro=wh_metro,
            buyer=users["buyer"],
            accountant=users["accountant"],
            products=catalog_map,
        )
        customers_map = _seed_growing_company_sales(
            org=org,
            branch_hub=branch_hub,
            wh_hub=wh_hub,
            branch_metro=branch_metro,
            wh_metro=wh_metro,
            owner=owner,
            sales_mgr=users["sales"],
            accountant=users["accountant"],
            products=catalog_map,
        )
        _seed_growing_company_accounting(org, owner, users["accountant"])
        _seed_growing_company_recurring_and_reminders(
            org=org,
            wh_hub=wh_hub,
            owner=owner,
            customer=customers_map["conti"],
            products=catalog_map,
        )

    return org
