"""Tests for tenant-scoped dynamic payment methods.

Enforces AGENTS.md Section 8 & Section 2 Rule 6:
- Dynamic PaymentMethod(TenantModel) with process_mode (record_only, manual_verify, gateway).
- Tenant isolation: payment methods belong to a tenant and cannot cross organizations.
- Fee rates, settlement accounts, transaction ID and proof requirements.
- Backward compatibility: PaymentMethod.CASH and choices still accessible.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.core.tenant_context import tenant_context
from apps.customers.models import Customer
from apps.sales.models import Payment, PaymentMethod, PaymentProcessMode
from apps.sales.services import (
    create_payment_method,
    ensure_default_payment_methods,
    list_active_payment_methods,
    update_payment_method,
)
from apps.tenancy.models import Organization


@pytest.mark.django_db
class TestDynamicPaymentMethods:
    def test_payment_method_backward_compatibility(self) -> None:
        """PaymentMethod still provides legacy enum constants for backward compatibility."""
        assert PaymentMethod.CASH == "cash"
        assert PaymentMethod.BANK_TRANSFER == "bank_transfer"
        assert PaymentMethod.CREDIT_CARD == "credit_card"
        assert len(PaymentMethod.choices) >= 5

    def test_payment_method_crud_and_process_modes(self) -> None:
        """Create and update dynamic payment methods with specific process modes."""
        org = Organization.objects.create(name="Apex Retail", slug="apex-retail")

        # Create bKash mobile banking method with manual verify
        bkash = create_payment_method(
            organization=org,
            name="bKash Merchant",
            code="bkash",
            process_mode=PaymentProcessMode.MANUAL_VERIFY,
            fee_rate=Decimal("0.0150"),  # 1.5% fee
            requires_tx_id=True,
            requires_proof=False,
            is_default=False,
            sort_order=10,
        )
        assert bkash.pk is not None
        assert bkash.process_mode == "manual_verify"
        assert bkash.fee_rate == Decimal("0.0150")
        assert bkash.requires_tx_id is True

        # Update to gateway mode
        update_payment_method(payment_method=bkash, process_mode=PaymentProcessMode.GATEWAY)
        bkash.refresh_from_db()
        assert bkash.process_mode == "gateway"

    def test_payment_method_tenant_isolation(self) -> None:
        """Payment methods of tenant A are isolated from tenant B."""
        org_a = Organization.objects.create(name="Tenant A", slug="tenant-a")
        org_b = Organization.objects.create(name="Tenant B", slug="tenant-b")

        pm_a = create_payment_method(organization=org_a, name="Nagad", code="nagad")
        assert pm_a.organization == org_a

        # Tenant B can also create a method with code "nagad" without collision
        pm_b = create_payment_method(organization=org_b, name="Nagad", code="nagad")
        assert pm_b.organization == org_b
        assert pm_a.pk != pm_b.pk

        # Listing for Tenant A only sees Tenant A's methods
        methods_a = list_active_payment_methods(organization=org_a)
        assert pm_a in methods_a
        assert pm_b not in methods_a

    def test_ensure_default_payment_methods(self) -> None:
        """ensure_default_payment_methods creates standard cash and bank transfer methods."""
        org = Organization.objects.create(name="Dhaka Trading", slug="dhaka-trading")
        created = ensure_default_payment_methods(organization=org)
        assert len(created) == 2
        codes = {m.code for m in created}
        assert codes == {"cash", "bank_transfer"}

        # Running again is idempotent
        second_run = ensure_default_payment_methods(organization=org)
        assert len(second_run) == 2
        with tenant_context(org):
            assert PaymentMethod.objects.filter(code__in=["cash", "bank_transfer"]).count() == 2

    def test_link_payment_method_record_to_payment(self) -> None:
        """Payments can be linked directly to a dynamic PaymentMethod record."""
        org = Organization.objects.create(name="Chittagong Corp", slug="ctg-corp")
        cust = Customer.objects.create(organization=org, name="Karim", email="karim@bms.local")
        pm = create_payment_method(
            organization=org,
            name="Bank Wire",
            code="bank_wire",
            process_mode=PaymentProcessMode.MANUAL_VERIFY,
            requires_tx_id=True,
        )

        payment = Payment.objects.create(
            organization=org,
            customer=cust,
            payment_number="PAY-0001",
            amount=Decimal("1500.00"),
            currency="BDT",
            payment_method="bank_wire",
            payment_method_record=pm,
        )

        assert payment.payment_method_record == pm
        assert payment.payment_method_record.process_mode == "manual_verify"
