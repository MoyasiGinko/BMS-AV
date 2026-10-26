"""Management command to seed realistic demo organizations for demonstration and testing."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from allauth.account.models import EmailAddress
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
from apps.crm import services as crm_services
from apps.crm.models import InteractionType, LeadSource, LeadStatus, TaskPriority
from apps.customers import services as customers_services
from apps.customers.models import Customer
from apps.hr import services as hr_services
from apps.hr.models import (
    AttendanceRecord,
    AttendanceSource,
    AttendanceStatus,
    Employee,
    EmployeeStatus,
    EmploymentType,
    LeaveRequest,
    LeaveType,
    Position,
    Shift,
)
from apps.inventory import services as inventory_services
from apps.payroll import services as payroll_services
from apps.payroll.models import (
    CalculationType,
    SalaryComponentType,
)
from apps.payroll.models import PaymentMethod as PayrollPaymentMethod
from apps.pos import services as pos_services
from apps.pos.models import POSRegister
from apps.purchasing import services as purchasing_services
from apps.purchasing.models import Supplier, SupplierPaymentMethod
from apps.sales import services as sales_services
from apps.sales.models import PaymentMethod, RecurringFrequency
from apps.tenancy.models import Branch, Department, Membership, Organization, Role, TaxCode, Warehouse
from apps.tenancy.services import provision_organization


class Command(BaseCommand):
    help = (
        "Seeds realistic demo organizations (Small Shop, Growing Company, People, Full ERP) "
        "with demo12345 users."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--target",
            type=str,
            default="all",
            help="Target organization: 'small_shop', 'growing_company', 'people', or 'all' (default: all)",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing demo organization before seeding if it already exists.",
        )
        parser.add_argument(
            "--noinput",
            "--no-input",
            action="store_true",
            help="Do not prompt for input or confirmation.",
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

        if target in ("all", "growing_company", "growing-company", "people"):
            self.stdout.write("Seeding 'Growing Company' organization (Apex Industrial Wholesale)...")
            org_growth = seed_growing_company(reset=reset, stdout_write=self.stdout.write)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully seeded '{org_growth.name}' ({org_growth.slug})! "
                    "Ready for multi-warehouse purchasing, sales, accounting, and people (HR/Payroll/CRM)."
                )
            )
        self.stdout.write("Provisioning platform superadmin user...")
        superadmin = _create_superuser("admin@businessos.com", "Platform Superadmin")
        self.stdout.write(
            self.style.SUCCESS(
                f"Platform superadmin '{superadmin.email}' provisioned (is_staff=True, is_superuser=True)."
            )
        )


def _create_superuser(email: str = "admin@businessos.com", name: str = "Platform Superadmin") -> User:
    u, _ = User.objects.get_or_create(
        email=email,
        defaults={"name": name, "is_active": True, "is_staff": True, "is_superuser": True},
    )
    u.name = name
    u.is_staff = True
    u.is_superuser = True
    u.is_active = True
    u.set_password("demo12345")
    u.save()
    EmailAddress.objects.get_or_create(
        user=u,
        email=email,
        defaults={"verified": True, "primary": True},
    )
    return u


def _create_user(email: str, name: str) -> User:
    u, _ = User.objects.get_or_create(
        email=email,
        defaults={"name": name, "is_active": True},
    )
    u.set_password("demo12345")
    u.save()
    EmailAddress.objects.get_or_create(
        user=u,
        email=email,
        defaults={"verified": True, "primary": True},
    )
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

    inventory_services.receive_stock(
        organization=org,
        warehouse=wh_hub,
        product=p_helm,
        quantity=Decimal("25.0000"),
        unit_cost=p_helm.cost_price,
        notes="Counter terminal floor stock",
        actor=buyer,
    )
    inventory_services.receive_stock(
        organization=org,
        warehouse=wh_hub,
        product=p_vest,
        quantity=Decimal("25.0000"),
        unit_cost=p_vest.cost_price,
        notes="Counter terminal floor stock",
        actor=buyer,
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


def _seed_people_users_and_roles(org: Organization) -> dict[str, User]:
    """Seed dedicated users and roles for people management personas."""
    hr_mgr = _create_user("hr.manager@apex.com", "Hannah Rivers")
    payroll_acc = _create_user("payroll@apex.com", "Peter Payroll")
    sarah_dev = _create_user("sarah.dev@apex.com", "Sarah Developer")
    alex_rep = _create_user("alex.rep@apex.com", "Alex Representative")

    role_hr_mgr, _ = Role.all_tenants.get_or_create(
        organization=org,
        name="HR Manager",
        defaults={
            "description": "Full HR management and sensitive PII access",
            "permissions": ["hr.*", "payroll.*", "reports.view", "hr.view_sensitive"],
        },
    )
    if "hr.view_sensitive" not in role_hr_mgr.permissions:
        role_hr_mgr.permissions = ["hr.*", "payroll.*", "reports.view", "hr.view_sensitive"]
        role_hr_mgr.save()

    role_payroll_acc, _ = Role.all_tenants.get_or_create(
        organization=org,
        name="Payroll Accountant",
        defaults={
            "description": "Payroll administration and reporting",
            "permissions": ["payroll.*", "reports.view", "accounting.view"],
        },
    )

    role_crm_agent, _ = Role.all_tenants.get_or_create(
        organization=org,
        name="Sales Representative",
        defaults={
            "description": "CRM pipeline, deals, and lead management",
            "permissions": ["crm.*", "customers.*"],
        },
    )

    role_member = Role.all_tenants.filter(organization=org, name="Member").first()
    if not role_member:
        role_member, _ = Role.all_tenants.get_or_create(
            organization=org,
            name="Member",
            defaults={"description": "Standard team member with self-service access", "permissions": []},
        )

    Membership.all_tenants.get_or_create(
        organization=org,
        user=hr_mgr,
        defaults={"role": role_hr_mgr, "status": Membership.STATUS_ACTIVE},
    )
    Membership.all_tenants.get_or_create(
        organization=org,
        user=payroll_acc,
        defaults={"role": role_payroll_acc, "status": Membership.STATUS_ACTIVE},
    )
    Membership.all_tenants.get_or_create(
        organization=org,
        user=sarah_dev,
        defaults={"role": role_member, "status": Membership.STATUS_ACTIVE},
    )
    Membership.all_tenants.get_or_create(
        organization=org,
        user=alex_rep,
        defaults={"role": role_crm_agent, "status": Membership.STATUS_ACTIVE},
    )

    return {
        "hr_mgr": hr_mgr,
        "payroll_acc": payroll_acc,
        "sarah_dev": sarah_dev,
        "alex_rep": alex_rep,
    }


def _seed_people_crm(org: Organization, owner: User, alex_rep: User) -> None:
    """Seed CRM pipelines, stages, leads, opportunities, interactions, and tasks."""
    pipeline = crm_services.seed_default_pipeline(organization=org, actor=owner)
    stage_proposal = pipeline.stages.filter(code="proposal").first()
    stage_negotiation = pipeline.stages.filter(code="negotiation").first()
    stage_won = pipeline.stages.filter(code="closed-won").first()

    lead_vance = crm_services.create_lead(
        organization=org,
        first_name="Marcus",
        last_name="Vance",
        company_name="Vance Heavy Industries",
        email="m.vance@vanceheavy.com",
        phone="+1-555-0101",
        title="Procurement Director",
        source=LeadSource.EVENT,
        status=LeadStatus.CONTACTED,
        estimated_value=Decimal("75000.00"),
        assigned_to=alex_rep,
        notes="Met at International Manufacturing Expo. Needs bulk tooling quotes.",
        tag_names=["Enterprise", "High Priority"],
        actor=alex_rep,
    )
    lead_nordic = crm_services.create_lead(
        organization=org,
        first_name="Elena",
        last_name="Rostova",
        company_name="Nordic Construction Supply",
        email="elena@nordicsupply.no",
        phone="+1-555-0102",
        title="Managing Partner",
        source=LeadSource.WEBSITE,
        status=LeadStatus.NEW,
        estimated_value=Decimal("42000.00"),
        assigned_to=alex_rep,
        notes="Inbound inquiry for protective safety gear and packaging.",
        tag_names=["High Priority"],
        actor=alex_rep,
    )

    cust = Customer.all_tenants.filter(organization=org).first()
    default_stage = pipeline.stages.first()
    assert default_stage is not None
    opp_stage_1 = stage_proposal or default_stage
    opp_stage_2 = stage_negotiation or default_stage
    opp_fleet = crm_services.create_opportunity(
        organization=org,
        title="Fleet Tooling Modernization 2026",
        pipeline=pipeline,
        stage=opp_stage_1,
        customer=cust,
        expected_value=Decimal("85000.00"),
        currency="USD",
        probability_percent=75,
        expected_close_date=timezone.now().date() + datetime.timedelta(days=30),
        assigned_to=alex_rep,
        notes="Submitted custom proposal with 3-year maintenance warranty.",
        tag_names=["Enterprise"],
        actor=alex_rep,
    )
    crm_services.create_opportunity(
        organization=org,
        title="Warehouse Safety Bulk Contract",
        pipeline=pipeline,
        stage=opp_stage_2,
        customer=cust,
        expected_value=Decimal("48000.00"),
        currency="USD",
        probability_percent=90,
        expected_close_date=timezone.now().date() + datetime.timedelta(days=14),
        assigned_to=alex_rep,
        notes="Final price negotiations with safety board committee.",
        actor=alex_rep,
    )
    if stage_won:
        crm_services.create_opportunity(
            organization=org,
            title="Hydraulic Presses Overhaul",
            pipeline=pipeline,
            stage=stage_won,
            customer=cust,
            expected_value=Decimal("32000.00"),
            currency="USD",
            probability_percent=100,
            assigned_to=alex_rep,
            notes="Contract signed and initial deposit received.",
            actor=alex_rep,
        )

    crm_services.log_interaction(
        organization=org,
        summary="Discovery call on heavy drill specifications",
        type=InteractionType.CALL,
        details="Client reviewed power output and safety certifications.",
        lead=lead_vance,
        actor=alex_rep,
    )
    crm_services.log_interaction(
        organization=org,
        summary="Proposal presentation with VP Operations",
        type=InteractionType.MEETING,
        details="Walked through pricing tiers and warranty terms.",
        opportunity=opp_fleet,
        actor=alex_rep,
    )
    crm_services.create_crm_task(
        organization=org,
        title="Send finalized tooling warranty contract",
        description="Attach SLA addendum requested during presentation.",
        due_date=timezone.now().date() + datetime.timedelta(days=2),
        priority=TaskPriority.HIGH,
        assigned_to=alex_rep,
        opportunity=opp_fleet,
        actor=alex_rep,
    )
    crm_services.create_crm_task(
        organization=org,
        title="Follow up with Nordic Supply regarding sample shipment",
        description="Confirm arrival of safety gear samples.",
        due_date=timezone.now().date() + datetime.timedelta(days=4),
        priority=TaskPriority.MEDIUM,
        assigned_to=alex_rep,
        lead=lead_nordic,
        actor=alex_rep,
    )


def _seed_people_hr(
    org: Organization,
    owner: User,
    people_users: dict[str, User],
    staff_users: dict[str, User],
) -> dict[str, Any]:
    """Seed HR departments, positions, shifts, and employee profiles."""
    branch_hub = Branch.all_tenants.filter(organization=org, code="HUB-01").first()

    dept_exec, _ = Department.all_tenants.get_or_create(
        organization=org,
        name="Executive & Administration",
        defaults={"code": "EXEC", "branch": branch_hub, "is_active": True},
    )
    dept_eng, _ = Department.all_tenants.get_or_create(
        organization=org,
        name="Engineering & Technology",
        defaults={"code": "ENG", "branch": branch_hub, "is_active": True},
    )
    dept_sales, _ = Department.all_tenants.get_or_create(
        organization=org,
        name="Sales & Commercial",
        defaults={"code": "SALES", "branch": branch_hub, "is_active": True},
    )
    dept_ops, _ = Department.all_tenants.get_or_create(
        organization=org,
        name="Operations & Fulfillment",
        defaults={"code": "OPS", "branch": branch_hub, "is_active": True},
    )

    pos_ceo, _ = Position.all_tenants.get_or_create(
        organization=org,
        code="CEO",
        defaults={
            "title": "Chief Executive Officer",
            "department": dept_exec,
            "min_salary": Decimal("120000.00"),
            "max_salary": Decimal("200000.00"),
        },
    )
    pos_hr_dir, _ = Position.all_tenants.get_or_create(
        organization=org,
        code="HR-DIR",
        defaults={
            "title": "Director of Human Resources",
            "department": dept_exec,
            "min_salary": Decimal("75000.00"),
            "max_salary": Decimal("120000.00"),
        },
    )
    pos_pay_spec, _ = Position.all_tenants.get_or_create(
        organization=org,
        code="PAY-SPEC",
        defaults={
            "title": "Senior Payroll Specialist",
            "department": dept_exec,
            "min_salary": Decimal("50000.00"),
            "max_salary": Decimal("85000.00"),
        },
    )
    pos_eng_sr, _ = Position.all_tenants.get_or_create(
        organization=org,
        code="ENG-SR",
        defaults={
            "title": "Staff Software Engineer",
            "department": dept_eng,
            "min_salary": Decimal("85000.00"),
            "max_salary": Decimal("140000.00"),
        },
    )
    pos_sales_rep, _ = Position.all_tenants.get_or_create(
        organization=org,
        code="SALES-REP",
        defaults={
            "title": "Senior Sales Account Executive",
            "department": dept_sales,
            "min_salary": Decimal("60000.00"),
            "max_salary": Decimal("110000.00"),
        },
    )
    pos_ops_lead, _ = Position.all_tenants.get_or_create(
        organization=org,
        code="OPS-LEAD",
        defaults={
            "title": "Warehouse Logistics Lead",
            "department": dept_ops,
            "min_salary": Decimal("45000.00"),
            "max_salary": Decimal("75000.00"),
        },
    )

    shift_day, _ = Shift.all_tenants.get_or_create(
        organization=org,
        name="Day Shift (08:00 - 17:00)",
        defaults={
            "start_time": datetime.time(8, 0),
            "end_time": datetime.time(17, 0),
            "break_minutes": 60,
            "is_overnight": False,
        },
    )
    shift_eve, _ = Shift.all_tenants.get_or_create(
        organization=org,
        name="Evening Logistics Shift (16:00 - 00:00)",
        defaults={
            "start_time": datetime.time(16, 0),
            "end_time": datetime.time(0, 0),
            "break_minutes": 45,
            "is_overnight": False,
        },
    )

    emp_ceo = Employee.all_tenants.filter(organization=org, code="EMP-0001").first()
    if not emp_ceo:
        emp_ceo = hr_services.create_employee(
            organization=org,
            first_name="Alex",
            last_name="Vance",
            code="EMP-0001",
            hire_date=datetime.date(2021, 1, 15),
            position=pos_ceo,
            department=dept_exec,
            branch=branch_hub,
            user=owner,
            work_email="owner@apexwholesale.com",
            personal_email="alex.vance.personal@example.com",
            phone="+1-555-0100",
            national_id="US-SSN-901-23-4567",
            bank_account="US-CHASE-9876543210",
            employment_type=EmploymentType.FULL_TIME,
            status=EmployeeStatus.ACTIVE,
            default_shift=shift_day,
            actor=owner,
        )

    emp_hr = Employee.all_tenants.filter(organization=org, code="EMP-0002").first()
    if not emp_hr:
        emp_hr = hr_services.create_employee(
            organization=org,
            first_name="Hannah",
            last_name="Rivers",
            code="EMP-0002",
            hire_date=datetime.date(2022, 3, 1),
            position=pos_hr_dir,
            department=dept_exec,
            branch=branch_hub,
            user=people_users["hr_mgr"],
            work_email="hr.manager@apex.com",
            personal_email="hannah.rivers@example.com",
            phone="+1-555-0102",
            national_id="US-SSN-812-34-5678",
            bank_account="US-WELLS-1234567890",
            employment_type=EmploymentType.FULL_TIME,
            status=EmployeeStatus.ACTIVE,
            manager=emp_ceo,
            default_shift=shift_day,
            actor=owner,
        )

    emp_pay = Employee.all_tenants.filter(organization=org, code="EMP-0003").first()
    if not emp_pay:
        emp_pay = hr_services.create_employee(
            organization=org,
            first_name="Peter",
            last_name="Payroll",
            code="EMP-0003",
            hire_date=datetime.date(2022, 5, 10),
            position=pos_pay_spec,
            department=dept_exec,
            branch=branch_hub,
            user=people_users["payroll_acc"],
            work_email="payroll@apex.com",
            personal_email="peter.payroll@example.com",
            phone="+1-555-0103",
            national_id="US-SSN-723-45-6789",
            bank_account="US-BOFA-2345678901",
            employment_type=EmploymentType.FULL_TIME,
            status=EmployeeStatus.ACTIVE,
            manager=emp_hr,
            default_shift=shift_day,
            actor=owner,
        )

    emp_dev = Employee.all_tenants.filter(organization=org, code="EMP-0004").first()
    if not emp_dev:
        emp_dev = hr_services.create_employee(
            organization=org,
            first_name="Sarah",
            last_name="Developer",
            code="EMP-0004",
            hire_date=datetime.date(2023, 2, 1),
            position=pos_eng_sr,
            department=dept_eng,
            branch=branch_hub,
            user=people_users["sarah_dev"],
            work_email="sarah.dev@apex.com",
            personal_email="sarah.dev.personal@example.com",
            phone="+1-555-0104",
            national_id="US-SSN-634-56-7890",
            bank_account="US-CITI-3456789012",
            employment_type=EmploymentType.FULL_TIME,
            status=EmployeeStatus.ACTIVE,
            manager=emp_ceo,
            default_shift=shift_day,
            actor=owner,
        )

    emp_rep = Employee.all_tenants.filter(organization=org, code="EMP-0005").first()
    if not emp_rep:
        emp_rep = hr_services.create_employee(
            organization=org,
            first_name="Alex",
            last_name="Representative",
            code="EMP-0005",
            hire_date=datetime.date(2023, 4, 15),
            position=pos_sales_rep,
            department=dept_sales,
            branch=branch_hub,
            user=people_users["alex_rep"],
            work_email="alex.rep@apex.com",
            personal_email="alex.rep.personal@example.com",
            phone="+1-555-0105",
            national_id="US-SSN-545-67-8901",
            bank_account="US-PNC-4567890123",
            employment_type=EmploymentType.FULL_TIME,
            status=EmployeeStatus.ACTIVE,
            manager=emp_ceo,
            default_shift=shift_day,
            actor=owner,
        )

    emp_ops = Employee.all_tenants.filter(organization=org, code="EMP-0006").first()
    if not emp_ops:
        emp_ops = hr_services.create_employee(
            organization=org,
            first_name="Walter",
            last_name="Stock",
            code="EMP-0006",
            hire_date=datetime.date(2022, 8, 1),
            position=pos_ops_lead,
            department=dept_ops,
            branch=branch_hub,
            user=staff_users["warehouse"],
            work_email="warehouse@apexwholesale.com",
            personal_email="walter.stock@example.com",
            phone="+1-555-0106",
            national_id="US-SSN-456-78-9012",
            bank_account="US-TD-5678901234",
            employment_type=EmploymentType.FULL_TIME,
            status=EmployeeStatus.ACTIVE,
            manager=emp_ceo,
            default_shift=shift_eve,
            actor=owner,
        )

    return {
        "ceo": emp_ceo,
        "hr": emp_hr,
        "payroll": emp_pay,
        "dev": emp_dev,
        "rep": emp_rep,
        "ops": emp_ops,
        "shift_day": shift_day,
    }


def _seed_people_attendance_and_leave(
    org: Organization,
    owner: User,
    people_users: dict[str, User],
    employees: dict[str, Any],
) -> None:
    """Seed leave categories, balances, requests, and historical/active attendance."""
    all_employees = [
        employees["ceo"],
        employees["hr"],
        employees["payroll"],
        employees["dev"],
        employees["rep"],
        employees["ops"],
    ]

    lt_annual = LeaveType.all_tenants.filter(organization=org, code="ANNUAL").first()
    if not lt_annual:
        lt_annual = hr_services.create_leave_type(
            organization=org,
            name="Paid Annual Vacation",
            code="ANNUAL",
            is_paid=True,
            default_allowance_days=Decimal("20.00"),
            actor=owner,
        )
    lt_sick = LeaveType.all_tenants.filter(organization=org, code="SICK").first()
    if not lt_sick:
        lt_sick = hr_services.create_leave_type(
            organization=org,
            name="Paid Sick Leave",
            code="SICK",
            is_paid=True,
            default_allowance_days=Decimal("10.00"),
            actor=owner,
        )
    lt_unpaid = LeaveType.all_tenants.filter(organization=org, code="UNPAID").first()
    if not lt_unpaid:
        lt_unpaid = hr_services.create_leave_type(
            organization=org,
            name="Unpaid Leave of Absence",
            code="UNPAID",
            is_paid=False,
            default_allowance_days=Decimal("0.00"),
            actor=owner,
        )

    current_year = timezone.now().year
    for emp in all_employees:
        hr_services.initialize_employee_leave_balances(
            organization=org,
            employee=emp,
            year=current_year,
            actor=owner,
        )

    emp_dev = employees["dev"]
    emp_rep = employees["rep"]
    emp_ops = employees["ops"]

    # Approved leave request for Sarah Dev
    past_start = timezone.now().date() - datetime.timedelta(days=7)
    past_end = timezone.now().date() - datetime.timedelta(days=6)
    has_leave = LeaveRequest.all_tenants.filter(
        organization=org, employee=emp_dev, start_date=past_start
    ).exists()
    if not has_leave:
        req_sarah = hr_services.submit_leave_request(
            organization=org,
            employee=emp_dev,
            leave_type=lt_annual,
            start_date=past_start,
            end_date=past_end,
            reason="Family gathering vacation",
            actor=people_users["sarah_dev"],
        )
        hr_services.approve_leave_request(
            organization=org,
            leave_request=req_sarah,
            approver=people_users["hr_mgr"],
        )

    # Historical Attendance
    today = timezone.now().date()
    for day_offset in range(1, 11):
        record_date = today - datetime.timedelta(days=day_offset)
        if record_date.weekday() >= 5:
            continue
        for emp in [emp_dev, emp_rep, emp_ops]:
            if not AttendanceRecord.all_tenants.filter(
                organization=org, employee=emp, date=record_date
            ).exists():
                is_late = day_offset == 3 and emp == emp_dev
                ci_time = datetime.datetime.combine(
                    record_date,
                    datetime.time(8, 25 if is_late else 0),
                    tzinfo=timezone.get_current_timezone(),
                )
                co_time = datetime.datetime.combine(
                    record_date,
                    datetime.time(17, 0),
                    tzinfo=timezone.get_current_timezone(),
                )
                hr_services.record_manual_attendance(
                    organization=org,
                    employee=emp,
                    date=record_date,
                    check_in=ci_time,
                    check_out=co_time,
                    status=AttendanceStatus.LATE if is_late else AttendanceStatus.PRESENT,
                    notes="Automated attendance entry" if not is_late else "Late arrival due to traffic",
                    actor=people_users["hr_mgr"],
                )

    # Active Check-in for Sarah Dev today
    if not AttendanceRecord.all_tenants.filter(organization=org, employee=emp_dev, date=today).exists():
        now_dt = timezone.now().replace(hour=8, minute=10)
        AttendanceRecord.objects.create(
            organization=org,
            employee=emp_dev,
            shift=employees.get("shift_day"),
            date=today,
            check_in=now_dt,
            source=AttendanceSource.WEB,
            status=AttendanceStatus.PRESENT,
            created_by=people_users["sarah_dev"],
        )


def _seed_people_payroll(
    org: Organization,
    owner: User,
    payroll_acc: User,
    employees: dict[str, Any],
) -> None:
    """Seed salary components, structures, compensation assignments, and payroll runs."""
    comp_basic = payroll_services.SalaryComponent.all_tenants.filter(organization=org, code="BASIC").first()
    if not comp_basic:
        comp_basic = payroll_services.create_salary_component(
            organization=org,
            name="Base Salary",
            code="BASIC",
            component_type=SalaryComponentType.EARNING,
            is_taxable=True,
            actor=owner,
        )

    comp_hra = payroll_services.SalaryComponent.all_tenants.filter(organization=org, code="HRA").first()
    if not comp_hra:
        comp_hra = payroll_services.create_salary_component(
            organization=org,
            name="Housing Allowance",
            code="HRA",
            component_type=SalaryComponentType.EARNING,
            is_taxable=True,
            actor=owner,
        )

    comp_trans = payroll_services.SalaryComponent.all_tenants.filter(organization=org, code="TRANS").first()
    if not comp_trans:
        comp_trans = payroll_services.create_salary_component(
            organization=org,
            name="Transport Allowance",
            code="TRANS",
            component_type=SalaryComponentType.EARNING,
            is_taxable=False,
            actor=owner,
        )

    comp_tax = payroll_services.SalaryComponent.all_tenants.filter(organization=org, code="TAX").first()
    if not comp_tax:
        comp_tax = payroll_services.create_salary_component(
            organization=org,
            name="Payroll Income Tax",
            code="TAX",
            component_type=SalaryComponentType.DEDUCTION,
            is_taxable=False,
            actor=owner,
        )

    comp_health = payroll_services.SalaryComponent.all_tenants.filter(organization=org, code="HEALTH").first()
    if not comp_health:
        comp_health = payroll_services.create_salary_component(
            organization=org,
            name="Health Insurance Premium",
            code="HEALTH",
            component_type=SalaryComponentType.DEDUCTION,
            is_taxable=False,
            actor=owner,
        )

    struct_std = payroll_services.SalaryStructure.all_tenants.filter(
        organization=org, code="STD-CORP"
    ).first()
    if not struct_std:
        struct_std = payroll_services.create_salary_structure(
            organization=org,
            name="Corporate Standard Compensation",
            code="STD-CORP",
            description="Standard compensation formula for full-time staff",
            items_data=[
                {
                    "component": comp_basic,
                    "calculation_type": CalculationType.PERCENT_OF_BASIC,
                    "percentage": Decimal("60.00"),
                },
                {
                    "component": comp_hra,
                    "calculation_type": CalculationType.PERCENT_OF_BASIC,
                    "percentage": Decimal("25.00"),
                },
                {
                    "component": comp_trans,
                    "calculation_type": CalculationType.FIXED,
                    "amount": Decimal("300.00"),
                },
                {
                    "component": comp_tax,
                    "calculation_type": CalculationType.PERCENT_OF_BASIC,
                    "percentage": Decimal("10.00"),
                },
                {
                    "component": comp_health,
                    "calculation_type": CalculationType.FIXED,
                    "amount": Decimal("150.00"),
                },
            ],
            actor=owner,
        )

    current_year = timezone.now().year
    effective_date = datetime.date(current_year - 1, 1, 1)
    salaries = [
        (employees["ceo"], Decimal("12000.00")),
        (employees["hr"], Decimal("7500.00")),
        (employees["payroll"], Decimal("5200.00")),
        (employees["dev"], Decimal("8500.00")),
        (employees["rep"], Decimal("6000.00")),
        (employees["ops"], Decimal("4200.00")),
    ]
    for emp, salary in salaries:
        if not payroll_services.EmployeeSalaryAssignment.all_tenants.filter(
            organization=org, employee=emp, is_active=True
        ).exists():
            payroll_services.assign_employee_salary(
                organization=org,
                employee=emp,
                salary_structure=struct_std,
                base_salary=salary,
                effective_from=effective_date,
                payment_method=PayrollPaymentMethod.BANK_TRANSFER,
                bank_name="Corporate Payroll Bank",
                bank_account_number=f"ACC-{emp.code}",
                actor=owner,
            )

    today = timezone.now().date()
    first_of_this_month = today.replace(day=1)
    last_day_of_prev_month = first_of_this_month - datetime.timedelta(days=1)
    first_of_prev_month = last_day_of_prev_month.replace(day=1)

    if not payroll_services.PayrollRun.all_tenants.filter(
        organization=org, period_start=first_of_prev_month
    ).exists():
        run_past = payroll_services.create_payroll_run(
            organization=org,
            period_start=first_of_prev_month,
            period_end=last_day_of_prev_month,
            payment_date=last_day_of_prev_month,
            notes="Previous month regular payroll disbursement",
            actor=payroll_acc,
        )
        payroll_services.review_payroll_run(payroll_run=run_past, actor=payroll_acc)
        payroll_services.approve_payroll_run(payroll_run=run_past, actor=owner)
        payroll_services.pay_payroll_run(payroll_run=run_past, payment_account="1020", actor=owner)

    if not payroll_services.PayrollRun.all_tenants.filter(
        organization=org, period_start=first_of_this_month
    ).exists():
        next_month = (first_of_this_month.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        last_day_of_this_month = next_month - datetime.timedelta(days=1)
        run_curr = payroll_services.create_payroll_run(
            organization=org,
            period_start=first_of_this_month,
            period_end=last_day_of_this_month,
            payment_date=last_day_of_this_month,
            notes="Current month active payroll run",
            actor=payroll_acc,
        )
        payroll_services.review_payroll_run(payroll_run=run_curr, actor=payroll_acc)


def _seed_people_modules(
    org: Organization,
    users: dict[str, User],
    log: Any = None,
) -> None:
    """Seed CRM, HR core, Attendance, Leave, and Payroll data for Apex Industrial Wholesale."""
    write = log or (lambda msg: None)
    write("Seeding people modules (CRM, HR core, Attendance & Leave, Payroll)...")

    people_users = _seed_people_users_and_roles(org)
    _seed_people_crm(org, users["owner"], people_users["alex_rep"])
    employees = _seed_people_hr(org, users["owner"], people_users, users)
    _seed_people_attendance_and_leave(org, users["owner"], people_users, employees)
    _seed_people_payroll(org, users["owner"], people_users["payroll_acc"], employees)

    write("People modules seeding completed successfully.")


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
                "hr.manager@apex.com",
                "payroll@apex.com",
                "sarah.dev@apex.com",
                "alex.rep@apex.com",
            ]:
                u = User.objects.filter(email=email).first()
                if u:
                    u.set_password("demo12345")
                    u.save()
            users = _seed_growing_company_staff()
            with tenant_context(existing):
                _seed_people_modules(org=existing, users=users, log=log)
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
        _seed_people_modules(org=org, users=users, log=log)

    return org
