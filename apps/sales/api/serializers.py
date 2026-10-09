"""REST API serializers for the Sales and Invoicing module."""

from decimal import Decimal
from typing import Any

from rest_framework import serializers

from apps.catalog.models import Product, ProductVariant
from apps.customers.models import Customer
from apps.sales import services
from apps.sales.models import (
    CreditNote,
    CreditNoteLine,
    Invoice,
    InvoiceLine,
    Payment,
    PaymentAllocation,
    PaymentMethod,
    PaymentRefund,
    Quote,
    QuoteLine,
    SalesOrder,
    SalesOrderLine,
)
from apps.tenancy.models import Branch, Warehouse

# ============================================================================
# QUOTE SERIALIZERS
# ============================================================================


class QuoteLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = QuoteLine
        fields = [
            "id",
            "product",
            "product_name",
            "product_sku",
            "variant",
            "description",
            "quantity",
            "unit_price",
            "discount_percent",
            "discount_amount",
            "tax_rate",
            "tax_amount",
            "line_total",
            "sort_order",
        ]
        read_only_fields = ["id", "discount_amount", "tax_amount", "line_total"]


class QuoteSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    customer_code = serializers.CharField(source="customer.code", read_only=True)
    lines = QuoteLineSerializer(many=True, read_only=True)

    class Meta:
        model = Quote
        fields = [
            "id",
            "public_id",
            "quote_number",
            "customer",
            "customer_name",
            "customer_code",
            "branch",
            "warehouse",
            "date",
            "valid_until",
            "currency",
            "exchange_rate",
            "status",
            "subtotal",
            "discount_total",
            "tax_total",
            "grand_total",
            "notes",
            "terms",
            "lines",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "quote_number",
            "subtotal",
            "discount_total",
            "tax_total",
            "grand_total",
            "status",
            "created_at",
            "updated_at",
        ]


class QuoteLineInputSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.all_tenants.all())
    variant = serializers.PrimaryKeyRelatedField(
        queryset=ProductVariant.all_tenants.all(),
        required=False,
        allow_null=True,
    )
    description = serializers.CharField(required=False, allow_blank=True, default="")
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4, default=Decimal("1.0000"))
    unit_price = serializers.DecimalField(max_digits=18, decimal_places=4, required=False)
    discount_percent = serializers.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0.00"))
    tax_rate = serializers.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0.00"))


class QuoteCreateSerializer(serializers.Serializer):
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.all_tenants.all())
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.all_tenants.all(),
        required=False,
        allow_null=True,
    )
    warehouse = serializers.PrimaryKeyRelatedField(
        queryset=Warehouse.all_tenants.all(),
        required=False,
        allow_null=True,
    )
    date = serializers.DateField(required=False)
    valid_until = serializers.DateField(required=False, allow_null=True)
    currency = serializers.CharField(max_length=3, default="USD")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    terms = serializers.CharField(required=False, allow_blank=True, default="")
    lines = QuoteLineInputSerializer(many=True)

    def create(self, validated_data: dict[str, Any]) -> Quote:
        org = validated_data.pop("organization", None)
        user = validated_data.pop("created_by", None)
        lines_data = validated_data.pop("lines")

        # Resolve unit price defaults if missing
        for item in lines_data:
            if "unit_price" not in item:
                item["unit_price"] = item["product"].price

        return services.create_quote(
            organization=org,
            customer=validated_data["customer"],
            lines=lines_data,
            branch=validated_data.get("branch"),
            warehouse=validated_data.get("warehouse"),
            date=validated_data.get("date"),
            valid_until=validated_data.get("valid_until"),
            currency=validated_data.get("currency", "USD"),
            notes=validated_data.get("notes", ""),
            terms=validated_data.get("terms", ""),
            actor=user,
        )


# ============================================================================
# SALES ORDER SERIALIZERS
# ============================================================================


class SalesOrderLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = SalesOrderLine
        fields = [
            "id",
            "product",
            "product_name",
            "product_sku",
            "variant",
            "description",
            "quantity",
            "delivered_quantity",
            "invoiced_quantity",
            "unit_price",
            "discount_percent",
            "discount_amount",
            "tax_rate",
            "tax_amount",
            "line_total",
            "sort_order",
        ]
        read_only_fields = [
            "id",
            "delivered_quantity",
            "invoiced_quantity",
            "discount_amount",
            "tax_amount",
            "line_total",
        ]


class SalesOrderSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    customer_code = serializers.CharField(source="customer.code", read_only=True)
    lines = SalesOrderLineSerializer(many=True, read_only=True)

    class Meta:
        model = SalesOrder
        fields = [
            "id",
            "public_id",
            "order_number",
            "customer",
            "customer_name",
            "customer_code",
            "branch",
            "warehouse",
            "quote",
            "order_date",
            "expected_delivery",
            "currency",
            "exchange_rate",
            "status",
            "subtotal",
            "discount_total",
            "tax_total",
            "grand_total",
            "notes",
            "terms",
            "lines",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "order_number",
            "subtotal",
            "discount_total",
            "tax_total",
            "grand_total",
            "status",
            "created_at",
            "updated_at",
        ]


class SalesOrderCreateSerializer(serializers.Serializer):
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.all_tenants.all())
    warehouse = serializers.PrimaryKeyRelatedField(
        queryset=Warehouse.all_tenants.all(),
        required=False,
        allow_null=True,
    )
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.all_tenants.all(),
        required=False,
        allow_null=True,
    )
    order_date = serializers.DateField(required=False)
    expected_delivery = serializers.DateField(required=False, allow_null=True)
    currency = serializers.CharField(max_length=3, default="USD")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    terms = serializers.CharField(required=False, allow_blank=True, default="")
    lines = QuoteLineInputSerializer(many=True)

    def create(self, validated_data: dict[str, Any]) -> SalesOrder:
        org = validated_data.pop("organization", None)
        user = validated_data.pop("created_by", None)
        lines_data = validated_data.pop("lines")

        for item in lines_data:
            if "unit_price" not in item:
                item["unit_price"] = item["product"].price

        return services.create_sales_order(
            organization=org,
            customer=validated_data["customer"],
            warehouse=validated_data.get("warehouse"),
            lines=lines_data,
            branch=validated_data.get("branch"),
            order_date=validated_data.get("order_date"),
            expected_delivery=validated_data.get("expected_delivery"),
            currency=validated_data.get("currency", "USD"),
            notes=validated_data.get("notes", ""),
            terms=validated_data.get("terms", ""),
            actor=user,
        )


# ============================================================================
# INVOICE SERIALIZERS
# ============================================================================


class InvoiceLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = InvoiceLine
        fields = [
            "id",
            "product",
            "product_name",
            "product_sku",
            "variant",
            "description",
            "quantity",
            "unit_price",
            "discount_percent",
            "discount_amount",
            "tax_rate",
            "tax_amount",
            "line_total",
            "unit_cost",
            "sort_order",
        ]
        read_only_fields = [
            "id",
            "discount_amount",
            "tax_amount",
            "line_total",
            "unit_cost",
        ]


class InvoiceSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    customer_code = serializers.CharField(source="customer.code", read_only=True)
    lines = InvoiceLineSerializer(many=True, read_only=True)

    class Meta:
        model = Invoice
        fields = [
            "id",
            "public_id",
            "invoice_number",
            "customer",
            "customer_name",
            "customer_code",
            "branch",
            "warehouse",
            "order",
            "invoice_date",
            "due_date",
            "currency",
            "exchange_rate",
            "status",
            "subtotal",
            "discount_total",
            "tax_total",
            "grand_total",
            "amount_paid",
            "balance_due",
            "journal_entry",
            "notes",
            "terms",
            "lines",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "invoice_number",
            "subtotal",
            "discount_total",
            "tax_total",
            "grand_total",
            "amount_paid",
            "balance_due",
            "status",
            "journal_entry",
            "created_at",
            "updated_at",
        ]


class InvoiceCreateSerializer(serializers.Serializer):
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.all_tenants.all())
    warehouse = serializers.PrimaryKeyRelatedField(
        queryset=Warehouse.all_tenants.all(),
        required=False,
        allow_null=True,
    )
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.all_tenants.all(),
        required=False,
        allow_null=True,
    )
    invoice_date = serializers.DateField(required=False)
    due_date = serializers.DateField(required=False, allow_null=True)
    currency = serializers.CharField(max_length=3, default="USD")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    terms = serializers.CharField(required=False, allow_blank=True, default="")
    lines = QuoteLineInputSerializer(many=True)

    def create(self, validated_data: dict[str, Any]) -> Invoice:
        org = validated_data.pop("organization", None)
        user = validated_data.pop("created_by", None)
        lines_data = validated_data.pop("lines")

        for item in lines_data:
            if "unit_price" not in item:
                item["unit_price"] = item["product"].price

        return services.create_invoice(
            organization=org,
            customer=validated_data["customer"],
            warehouse=validated_data.get("warehouse"),
            lines=lines_data,
            branch=validated_data.get("branch"),
            invoice_date=validated_data.get("invoice_date"),
            due_date=validated_data.get("due_date"),
            currency=validated_data.get("currency", "USD"),
            notes=validated_data.get("notes", ""),
            terms=validated_data.get("terms", ""),
            actor=user,
        )


class InvoiceVoidActionSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="Voided via API")


# ============================================================================
# CREDIT NOTE SERIALIZERS
# ============================================================================


class CreditNoteLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = CreditNoteLine
        fields = [
            "id",
            "product",
            "product_name",
            "product_sku",
            "variant",
            "description",
            "quantity",
            "unit_price",
            "tax_rate",
            "tax_amount",
            "line_total",
            "restock",
            "unit_cost",
            "sort_order",
        ]
        read_only_fields = ["id", "tax_amount", "line_total", "unit_cost"]


class CreditNoteSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    customer_code = serializers.CharField(source="customer.code", read_only=True)
    lines = CreditNoteLineSerializer(many=True, read_only=True)

    class Meta:
        model = CreditNote
        fields = [
            "id",
            "public_id",
            "credit_note_number",
            "customer",
            "customer_name",
            "customer_code",
            "branch",
            "warehouse",
            "invoice",
            "credit_note_date",
            "currency",
            "exchange_rate",
            "status",
            "subtotal",
            "tax_total",
            "grand_total",
            "journal_entry",
            "reason",
            "notes",
            "lines",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "credit_note_number",
            "subtotal",
            "tax_total",
            "grand_total",
            "status",
            "journal_entry",
            "created_at",
            "updated_at",
        ]


class CreditNoteCreateSerializer(serializers.Serializer):
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.all_tenants.all())
    warehouse = serializers.PrimaryKeyRelatedField(
        queryset=Warehouse.all_tenants.all(),
        required=False,
        allow_null=True,
    )
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.all_tenants.all(),
        required=False,
        allow_null=True,
    )
    invoice = serializers.PrimaryKeyRelatedField(
        queryset=Invoice.all_tenants.all(),
        required=False,
        allow_null=True,
    )
    credit_note_date = serializers.DateField(required=False)
    currency = serializers.CharField(max_length=3, default="USD")
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    lines = QuoteLineInputSerializer(many=True)

    def create(self, validated_data: dict[str, Any]) -> CreditNote:
        org = validated_data.pop("organization", None)
        user = validated_data.pop("created_by", None)
        lines_data = validated_data.pop("lines")

        for item in lines_data:
            if "unit_price" not in item:
                item["unit_price"] = item["product"].price

        return services.create_credit_note(
            organization=org,
            customer=validated_data["customer"],
            warehouse=validated_data.get("warehouse"),
            lines=lines_data,
            branch=validated_data.get("branch"),
            invoice=validated_data.get("invoice"),
            credit_note_date=validated_data.get("credit_note_date"),
            currency=validated_data.get("currency", "USD"),
            reason=validated_data.get("reason", ""),
            notes=validated_data.get("notes", ""),
            actor=user,
        )


# ============================================================================
# CUSTOMER PAYMENT SERIALIZERS
# ============================================================================


class PaymentAllocationSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(source="invoice.invoice_number", read_only=True)

    class Meta:
        model = PaymentAllocation
        fields = [
            "id",
            "invoice",
            "invoice_number",
            "amount",
            "created_at",
        ]
        read_only_fields = ["id", "invoice_number", "created_at"]


class PaymentRefundSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentRefund
        fields = [
            "id",
            "refund_number",
            "amount",
            "refund_date",
            "reason",
            "journal_entry",
            "created_at",
        ]
        read_only_fields = ["id", "refund_number", "journal_entry", "created_at"]


class PaymentSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    customer_code = serializers.CharField(source="customer.code", read_only=True)
    allocations = PaymentAllocationSerializer(many=True, read_only=True)
    refunds = PaymentRefundSerializer(many=True, read_only=True)
    refunded_amount = serializers.DecimalField(max_digits=18, decimal_places=4, read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "public_id",
            "payment_number",
            "customer",
            "customer_name",
            "customer_code",
            "branch",
            "payment_date",
            "payment_method",
            "amount",
            "allocated_amount",
            "unallocated_amount",
            "refunded_amount",
            "currency",
            "exchange_rate",
            "status",
            "reference",
            "notes",
            "journal_entry",
            "allocations",
            "refunds",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "payment_number",
            "allocated_amount",
            "unallocated_amount",
            "refunded_amount",
            "status",
            "journal_entry",
            "allocations",
            "refunds",
            "created_at",
            "updated_at",
        ]


class PaymentAllocationItemSerializer(serializers.Serializer):
    invoice = serializers.PrimaryKeyRelatedField(queryset=Invoice.all_tenants.all())
    amount = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))


class PaymentCreateSerializer(serializers.Serializer):
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.all_tenants.all())
    amount = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.01"))
    payment_method = serializers.ChoiceField(
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH,
    )
    payment_date = serializers.DateField(required=False)
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.all_tenants.all(),
        required=False,
        allow_null=True,
    )
    currency = serializers.CharField(max_length=3, default="USD")
    reference = serializers.CharField(required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    allocations = PaymentAllocationItemSerializer(many=True, required=False)

    def create(self, validated_data: dict[str, Any]) -> Payment:
        org = validated_data.pop("organization", None)
        user = validated_data.pop("created_by", None)
        raw_allocations = validated_data.pop("allocations", None)

        allocations = None
        if raw_allocations:
            allocations = [
                {"invoice_id": item["invoice"].pk, "amount": item["amount"]} for item in raw_allocations
            ]

        return services.receive_payment(
            organization=org,
            customer=validated_data["customer"],
            amount=validated_data["amount"],
            payment_method=validated_data.get("payment_method", PaymentMethod.CASH),
            payment_date=validated_data.get("payment_date"),
            allocations=allocations,
            branch=validated_data.get("branch"),
            currency=validated_data.get("currency", "USD"),
            reference=validated_data.get("reference", ""),
            notes=validated_data.get("notes", ""),
            actor=user,
        )


class PaymentAllocateActionSerializer(serializers.Serializer):
    allocations = PaymentAllocationItemSerializer(many=True)


class PaymentRefundActionSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.01"))
    refund_date = serializers.DateField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class PaymentVoidActionSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="")
