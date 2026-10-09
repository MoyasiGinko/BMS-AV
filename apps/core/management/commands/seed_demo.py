"""Management command to seed realistic demo organizations for demonstration and testing."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounting import services as accounting_services
from apps.accounts.models import User
from apps.billing.services import seed_default_plans
from apps.catalog.models import Category, Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.customers import services as customers_services
from apps.customers.models import Customer
from apps.inventory import services as inventory_services
from apps.pos import services as pos_services
from apps.pos.models import POSRegister
from apps.sales import services as sales_services
from apps.sales.models import PaymentMethod
from apps.tenancy.models import Branch, Membership, Organization, Role, TaxCode, Warehouse
from apps.tenancy.services import provision_organization


class Command(BaseCommand):
    help = "Seeds realistic demo organizations (Small Shop, Growing Company, Full ERP) with demo12345 users."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--target",
            type=str,
            default="all",
            help="Target organization to seed: 'small_shop', or 'all' (default: all)",
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
