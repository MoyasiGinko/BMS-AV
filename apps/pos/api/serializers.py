"""REST API serializers for the Point of Sale (POS) module."""

from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.pos.models import POSHeldCart, POSRegister, POSSale, POSShift
from apps.tenancy.models import Branch, Warehouse


class POSRegisterSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)

    class Meta:
        model = POSRegister
        fields = [
            "public_id",
            "name",
            "code",
            "branch",
            "branch_name",
            "warehouse",
            "warehouse_name",
            "receipt_header",
            "receipt_footer",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["public_id", "created_at", "updated_at"]


class POSRegisterCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    code = serializers.CharField(max_length=20, required=False, allow_blank=True)
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.all_tenants.all())
    warehouse = serializers.PrimaryKeyRelatedField(queryset=Warehouse.all_tenants.all())
    receipt_header = serializers.CharField(required=False, allow_blank=True, default="")
    receipt_footer = serializers.CharField(required=False, allow_blank=True, default="")
    is_active = serializers.BooleanField(default=True)


class POSShiftSerializer(serializers.ModelSerializer):
    register_code = serializers.CharField(source="register.code", read_only=True)
    register_name = serializers.CharField(source="register.name", read_only=True)
    cashier_name = serializers.CharField(source="cashier.get_full_name", read_only=True)

    class Meta:
        model = POSShift
        fields = [
            "public_id",
            "shift_number",
            "register",
            "register_code",
            "register_name",
            "cashier",
            "cashier_name",
            "status",
            "opened_at",
            "closed_at",
            "opening_cash",
            "closing_cash_counted",
            "expected_cash",
            "cash_variance",
            "total_sales_amount",
            "total_cash_sales",
            "total_card_sales",
            "total_other_sales",
            "notes",
            "created_at",
        ]
        read_only_fields = fields


class POSOpenShiftSerializer(serializers.Serializer):
    register = serializers.PrimaryKeyRelatedField(queryset=POSRegister.all_tenants.all())
    opening_cash = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0000"))
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class POSCloseShiftSerializer(serializers.Serializer):
    closing_cash_counted = serializers.DecimalField(
        max_digits=18, decimal_places=4, min_value=Decimal("0.0000")
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class POSSaleLineInputSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))
    unit_price = serializers.DecimalField(
        max_digits=18, decimal_places=4, min_value=Decimal("0.0000"), required=False
    )
    discount_percent = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0.00"),
        max_value=Decimal("100.00"),
        default=Decimal("0.00"),
    )
    tax_rate = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=Decimal("0.00"), default=Decimal("0.00"), required=False
    )


class POSTenderInputSerializer(serializers.Serializer):
    payment_method = serializers.CharField(max_length=20)
    amount = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))


class POSCheckoutSerializer(serializers.Serializer):
    shift_id = serializers.IntegerField()
    lines = POSSaleLineInputSerializer(many=True)
    payments = POSTenderInputSerializer(many=True)
    customer_id = serializers.IntegerField(required=False, allow_null=True)
    amount_tendered = serializers.DecimalField(
        max_digits=18, decimal_places=4, min_value=Decimal("0.0000"), required=False, allow_null=True
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class POSSaleSerializer(serializers.ModelSerializer):
    register_code = serializers.CharField(source="register.code", read_only=True)
    shift_number = serializers.CharField(source="shift.shift_number", read_only=True)
    invoice_number = serializers.CharField(source="invoice.invoice_number", read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True, default="Walk-in")

    class Meta:
        model = POSSale
        fields = [
            "public_id",
            "receipt_number",
            "register",
            "register_code",
            "shift",
            "shift_number",
            "invoice",
            "invoice_number",
            "customer",
            "customer_name",
            "total_amount",
            "amount_tendered",
            "change_given",
            "tenders",
            "created_at",
        ]
        read_only_fields = fields


class POSHeldCartSerializer(serializers.ModelSerializer):
    class Meta:
        model = POSHeldCart
        fields = [
            "id",
            "public_id",
            "cart_label",
            "cart_data",
            "total_amount",
            "created_at",
        ]
        read_only_fields = ["id", "public_id", "created_at"]
