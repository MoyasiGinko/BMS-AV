"""Tenant isolation tests for the POS module."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounting import services as accounting_services
from apps.pos import selectors, services
from apps.pos.exceptions import POSError
from apps.tenancy.models import Branch, Organization, Warehouse

User = get_user_model()


@pytest.fixture
def isolation_setup(db: None) -> dict[str, object]:
    org_a = Organization.objects.create(name="Org A POS", slug="org-a-pos")
    org_b = Organization.objects.create(name="Org B POS", slug="org-b-pos")

    user_a = User.objects.create_user(email="cashier_a@example.com")
    user_b = User.objects.create_user(email="cashier_b@example.com")

    accounting_services.seed_chart_of_accounts(organization=org_a)
    accounting_services.seed_fiscal_calendar(organization=org_a, year=timezone.now().year)

    accounting_services.seed_chart_of_accounts(organization=org_b)
    accounting_services.seed_fiscal_calendar(organization=org_b, year=timezone.now().year)

    branch_a = Branch.objects.create(organization=org_a, name="Branch A", code="BR-A")
    wh_a = Warehouse.objects.create(organization=org_a, name="Warehouse A", branch=branch_a)

    branch_b = Branch.objects.create(organization=org_b, name="Branch B", code="BR-B")
    wh_b = Warehouse.objects.create(organization=org_b, name="Warehouse B", branch=branch_b)

    reg_a = services.create_register(
        organization=org_a,
        name="Reg A",
        branch=branch_a,
        warehouse=wh_a,
        code="POS-A",
        actor=user_a,
    )
    reg_b = services.create_register(
        organization=org_b,
        name="Reg B",
        branch=branch_b,
        warehouse=wh_b,
        code="POS-B",
        actor=user_b,
    )

    shift_a = services.open_shift(
        organization=org_a,
        register=reg_a,
        cashier=user_a,
        opening_cash=Decimal("50.00"),
        actor=user_a,
    )
    shift_b = services.open_shift(
        organization=org_b,
        register=reg_b,
        cashier=user_b,
        opening_cash=Decimal("50.00"),
        actor=user_b,
    )

    return {
        "org_a": org_a,
        "org_b": org_b,
        "user_a": user_a,
        "user_b": user_b,
        "reg_a": reg_a,
        "reg_b": reg_b,
        "shift_a": shift_a,
        "shift_b": shift_b,
    }


def test_register_tenant_isolation(isolation_setup: dict[str, object]) -> None:
    org_a = isolation_setup["org_a"]  # type: ignore
    org_b = isolation_setup["org_b"]  # type: ignore
    reg_a = isolation_setup["reg_a"]  # type: ignore
    reg_b = isolation_setup["reg_b"]  # type: ignore

    # Scoped selectors
    regs_a = selectors.list_registers(organization=org_a)
    assert reg_a in regs_a
    assert reg_b not in regs_a

    regs_b = selectors.list_registers(organization=org_b)
    assert reg_b in regs_b
    assert reg_a not in regs_b

    # Direct get
    assert selectors.get_register(organization=org_a, register_id=reg_b.pk) is None


def test_shift_tenant_isolation(isolation_setup: dict[str, object]) -> None:
    org_a = isolation_setup["org_a"]  # type: ignore
    org_b = isolation_setup["org_b"]  # type: ignore
    shift_a = isolation_setup["shift_a"]  # type: ignore
    shift_b = isolation_setup["shift_b"]  # type: ignore

    shifts_a = selectors.list_shifts(organization=org_a)
    assert shift_a in shifts_a
    assert shift_b not in shifts_a

    shifts_b = selectors.list_shifts(organization=org_b)
    assert shift_b in shifts_b
    assert shift_a not in shifts_b

    assert selectors.get_shift(organization=org_a, public_id=shift_b.public_id) is None
    assert selectors.get_shift(organization=org_b, public_id=shift_a.public_id) is None


def test_held_cart_tenant_isolation(isolation_setup: dict[str, object]) -> None:
    org_a = isolation_setup["org_a"]  # type: ignore
    org_b = isolation_setup["org_b"]  # type: ignore
    shift_a = isolation_setup["shift_a"]  # type: ignore
    user_a = isolation_setup["user_a"]  # type: ignore

    cart_a = services.hold_cart(
        organization=org_a,
        shift=shift_a,
        cart_data={"test": 1},
        cart_label="Table 1",
        total_amount=Decimal("10.00"),
        actor=user_a,
    )

    # Attempt to resume Org A cart using Org B context fails
    with pytest.raises(POSError):
        services.resume_cart(
            organization=org_b,
            held_cart_id=cart_a.pk,
            actor=isolation_setup["user_b"],  # type: ignore
        )
