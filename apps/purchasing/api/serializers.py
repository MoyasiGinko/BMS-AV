"""REST API serializers for the Purchasing and Vendor Management module."""

from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.catalog.models import Product
from apps.purchasing.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseReturn,
    PurchaseReturnLine,
    Supplier,
    SupplierBill,
    SupplierBillLine,
    SupplierPayment,
    SupplierPaymentAllocation,
    SupplierPaymentMethod,
)
from apps.tenancy.models import Branch, Warehouse


class SupplierSerializer(serializers.ModelSerializer[Supplier]):
    class Meta:
        model = Supplier
        fields = [
            "id",
            "public_id",
            "code",
            "name",
            "contact_person",
            "email",
            "phone",
            "address",
            "city",
            "country",
            "postal_code",
            "tax_id",
            "currency",
            "payment_terms_days",
            "current_balance",
            "is_active",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "public_id", "current_balance", "created_at", "updated_at"]


class SupplierCreateSerializer(serializers.ModelSerializer[Supplier]):
    code = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = Supplier
        fields = [
            "code",
            "name",
            "contact_person",
            "email",
            "phone",
            "address",
            "city",
            "country",
            "postal_code",
            "tax_id",
            "currency",
            "payment_terms_days",
            "notes",
        ]


class PurchaseOrderLineSerializer(serializers.ModelSerializer[PurchaseOrderLine]):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = PurchaseOrderLine
        fields = [
            "id",
            "product",
            "product_name",
            "product_sku",
            "quantity",
            "received_quantity",
            "unit_price",
            "tax_rate",
            "subtotal",
            "tax_amount",
            "total_amount",
            "notes",
        ]
        read_only_fields = ["id", "received_quantity", "subtotal", "tax_amount", "total_amount"]


class PurchaseOrderLineInputSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.all_tenants.all())
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))
    unit_price = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0000"))
    tax_rate = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, default=Decimal("0.00")
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class PurchaseOrderSerializer(serializers.ModelSerializer[PurchaseOrder]):
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    lines = PurchaseOrderLineSerializer(many=True, read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = [
            "id",
            "public_id",
            "order_number",
            "supplier",
            "supplier_name",
            "branch",
            "warehouse",
            "order_date",
            "expected_date",
            "currency",
            "exchange_rate",
            "status",
            "subtotal",
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
            "status",
            "subtotal",
            "tax_total",
            "grand_total",
            "created_at",
            "updated_at",
        ]


class PurchaseOrderCreateSerializer(serializers.Serializer):
    supplier = serializers.PrimaryKeyRelatedField(queryset=Supplier.all_tenants.all())
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.all_tenants.all(), required=False, allow_null=True
    )
    warehouse = serializers.PrimaryKeyRelatedField(
        queryset=Warehouse.all_tenants.all(), required=False, allow_null=True
    )
    order_date = serializers.DateField(required=False)
    expected_date = serializers.DateField(required=False, allow_null=True)
    currency = serializers.CharField(max_length=3, required=False, default="USD")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    terms = serializers.CharField(required=False, allow_blank=True, default="")
    lines = PurchaseOrderLineInputSerializer(many=True)


class GoodsReceiptLineSerializer(serializers.ModelSerializer[GoodsReceiptLine]):
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = GoodsReceiptLine
        fields = [
            "id",
            "po_line",
            "product",
            "product_name",
            "quantity",
            "unit_cost",
            "total_cost",
        ]
        read_only_fields = ["id", "total_cost"]


class GoodsReceiptLineInputSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.all_tenants.all())
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))
    unit_cost = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0000"))
    po_line = serializers.PrimaryKeyRelatedField(
        queryset=PurchaseOrderLine.all_tenants.all(), required=False, allow_null=True
    )


class GoodsReceiptSerializer(serializers.ModelSerializer[GoodsReceipt]):
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    lines = GoodsReceiptLineSerializer(many=True, read_only=True)

    class Meta:
        model = GoodsReceipt
        fields = [
            "id",
            "public_id",
            "receipt_number",
            "purchase_order",
            "supplier",
            "supplier_name",
            "warehouse",
            "date",
            "status",
            "total_cost",
            "notes",
            "lines",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "receipt_number",
            "status",
            "total_cost",
            "created_at",
            "updated_at",
        ]


class GoodsReceiptCreateSerializer(serializers.Serializer):
    supplier = serializers.PrimaryKeyRelatedField(queryset=Supplier.all_tenants.all())
    warehouse = serializers.PrimaryKeyRelatedField(queryset=Warehouse.all_tenants.all())
    purchase_order = serializers.PrimaryKeyRelatedField(
        queryset=PurchaseOrder.all_tenants.all(), required=False, allow_null=True
    )
    date = serializers.DateField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    lines = GoodsReceiptLineInputSerializer(many=True)


class SupplierBillLineSerializer(serializers.ModelSerializer[SupplierBillLine]):
    product_name = serializers.CharField(source="product.name", read_only=True, default="")

    class Meta:
        model = SupplierBillLine
        fields = [
            "id",
            "product",
            "product_name",
            "description",
            "quantity",
            "unit_price",
            "tax_rate",
            "subtotal",
            "tax_amount",
            "total_amount",
        ]
        read_only_fields = ["id", "subtotal", "tax_amount", "total_amount"]


class SupplierBillLineInputSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(
        queryset=Product.all_tenants.all(), required=False, allow_null=True
    )
    description = serializers.CharField(max_length=255, required=False, allow_blank=True)
    quantity = serializers.DecimalField(
        max_digits=18, decimal_places=4, default=Decimal("1.0000"), min_value=Decimal("0.0001")
    )
    unit_price = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0000"))
    tax_rate = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, default=Decimal("0.00")
    )


class SupplierBillSerializer(serializers.ModelSerializer[SupplierBill]):
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    lines = SupplierBillLineSerializer(many=True, read_only=True)

    class Meta:
        model = SupplierBill
        fields = [
            "id",
            "public_id",
            "bill_number",
            "supplier_reference",
            "supplier",
            "supplier_name",
            "purchase_order",
            "goods_receipt",
            "issue_date",
            "due_date",
            "status",
            "currency",
            "subtotal",
            "tax_total",
            "total_amount",
            "balance_due",
            "notes",
            "lines",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "bill_number",
            "status",
            "subtotal",
            "tax_total",
            "total_amount",
            "balance_due",
            "created_at",
            "updated_at",
        ]


class SupplierBillCreateSerializer(serializers.Serializer):
    supplier = serializers.PrimaryKeyRelatedField(queryset=Supplier.all_tenants.all())
    due_date = serializers.DateField()
    issue_date = serializers.DateField(required=False)
    supplier_reference = serializers.CharField(required=False, allow_blank=True, default="")
    purchase_order = serializers.PrimaryKeyRelatedField(
        queryset=PurchaseOrder.all_tenants.all(), required=False, allow_null=True
    )
    goods_receipt = serializers.PrimaryKeyRelatedField(
        queryset=GoodsReceipt.all_tenants.all(), required=False, allow_null=True
    )
    currency = serializers.CharField(max_length=3, required=False, default="USD")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    lines = SupplierBillLineInputSerializer(many=True)


class SupplierPaymentAllocationSerializer(serializers.ModelSerializer[SupplierPaymentAllocation]):
    bill_number = serializers.CharField(source="bill.bill_number", read_only=True)

    class Meta:
        model = SupplierPaymentAllocation
        fields = ["id", "bill", "bill_number", "allocated_amount"]
        read_only_fields = ["id", "bill_number"]


class SupplierPaymentAllocationInputSerializer(serializers.Serializer):
    bill_id = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))


class SupplierPaymentSerializer(serializers.ModelSerializer[SupplierPayment]):
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    allocations = SupplierPaymentAllocationSerializer(many=True, read_only=True)

    class Meta:
        model = SupplierPayment
        fields = [
            "id",
            "public_id",
            "payment_number",
            "supplier",
            "supplier_name",
            "amount",
            "payment_date",
            "payment_method",
            "reference",
            "notes",
            "allocations",
            "created_at",
        ]
        read_only_fields = ["id", "public_id", "payment_number", "created_at"]


class SupplierPaymentCreateSerializer(serializers.Serializer):
    supplier = serializers.PrimaryKeyRelatedField(queryset=Supplier.all_tenants.all())
    amount = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))
    payment_method = serializers.ChoiceField(
        choices=SupplierPaymentMethod.choices, default=SupplierPaymentMethod.BANK_TRANSFER
    )
    payment_date = serializers.DateField(required=False)
    reference = serializers.CharField(required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    allocations = SupplierPaymentAllocationInputSerializer(many=True, required=False, default=list)


class PurchaseReturnLineSerializer(serializers.ModelSerializer[PurchaseReturnLine]):
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = PurchaseReturnLine
        fields = [
            "id",
            "product",
            "product_name",
            "quantity",
            "unit_price",
            "tax_rate",
            "subtotal",
            "tax_amount",
            "total_amount",
        ]
        read_only_fields = ["id", "subtotal", "tax_amount", "total_amount"]


class PurchaseReturnLineInputSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.all_tenants.all())
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))
    unit_price = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0000"))
    tax_rate = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, default=Decimal("0.00")
    )


class PurchaseReturnSerializer(serializers.ModelSerializer[PurchaseReturn]):
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    lines = PurchaseReturnLineSerializer(many=True, read_only=True)

    class Meta:
        model = PurchaseReturn
        fields = [
            "id",
            "public_id",
            "return_number",
            "supplier",
            "supplier_name",
            "warehouse",
            "goods_receipt",
            "bill",
            "return_date",
            "status",
            "subtotal",
            "tax_total",
            "total_amount",
            "reason",
            "lines",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "return_number",
            "status",
            "subtotal",
            "tax_total",
            "total_amount",
            "created_at",
            "updated_at",
        ]


class PurchaseReturnCreateSerializer(serializers.Serializer):
    supplier = serializers.PrimaryKeyRelatedField(queryset=Supplier.all_tenants.all())
    warehouse = serializers.PrimaryKeyRelatedField(queryset=Warehouse.all_tenants.all())
    goods_receipt = serializers.PrimaryKeyRelatedField(
        queryset=GoodsReceipt.all_tenants.all(), required=False, allow_null=True
    )
    bill = serializers.PrimaryKeyRelatedField(
        queryset=SupplierBill.all_tenants.all(), required=False, allow_null=True
    )
    return_date = serializers.DateField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    lines = PurchaseReturnLineInputSerializer(many=True)
