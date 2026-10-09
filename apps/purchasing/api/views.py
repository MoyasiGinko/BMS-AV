"""REST API viewsets for the Purchasing module."""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api.idempotency import IDEMPOTENCY_KEY_PARAMETER, idempotent
from apps.core.api.viewsets import TenantScopedModelViewSet
from apps.purchasing import services
from apps.purchasing.api.serializers import (
    GoodsReceiptCreateSerializer,
    GoodsReceiptSerializer,
    PurchaseOrderCreateSerializer,
    PurchaseOrderSerializer,
    PurchaseReturnCreateSerializer,
    PurchaseReturnSerializer,
    SupplierBillCreateSerializer,
    SupplierBillSerializer,
    SupplierCreateSerializer,
    SupplierPaymentCreateSerializer,
    SupplierPaymentSerializer,
    SupplierSerializer,
)
from apps.purchasing.models import (
    GoodsReceipt,
    PurchaseOrder,
    PurchaseReturn,
    Supplier,
    SupplierBill,
    SupplierPayment,
)


@extend_schema_view(
    list=extend_schema(tags=["Purchasing"], summary="List suppliers"),
    retrieve=extend_schema(tags=["Purchasing"], summary="Retrieve supplier"),
    create=extend_schema(tags=["Purchasing"], summary="Create supplier"),
    update=extend_schema(tags=["Purchasing"], summary="Update supplier"),
    partial_update=extend_schema(tags=["Purchasing"], summary="Partially update supplier"),
    destroy=extend_schema(tags=["Purchasing"], summary="Archive supplier"),
)
class SupplierViewSet(TenantScopedModelViewSet):
    """API endpoint for managing vendors and suppliers."""

    queryset = Supplier.all_tenants.all()
    serializer_class = SupplierSerializer
    lookup_field = "public_id"
    required_permission = "purchasing.view"
    search_fields = ["name", "code", "email", "phone"]
    ordering_fields = ["name", "code", "current_balance", "created_at"]
    ordering = ["name"]

    @extend_schema(
        tags=["Purchasing"],
        summary="Create supplier",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        request=SupplierCreateSerializer,
        responses={201: SupplierSerializer},
    )
    @idempotent
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = SupplierCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        supplier = services.create_supplier(
            organization=self.get_tenant(),
            name=data["name"],
            code=data.get("code") or None,
            contact_person=data.get("contact_person", ""),
            email=data.get("email", ""),
            phone=data.get("phone", ""),
            address=data.get("address", ""),
            city=data.get("city", ""),
            country=data.get("country", ""),
            postal_code=data.get("postal_code", ""),
            tax_id=data.get("tax_id", ""),
            currency=data.get("currency", "USD"),
            payment_terms_days=data.get("payment_terms_days", 30),
            notes=data.get("notes", ""),
            actor=request.user,
        )
        return Response(SupplierSerializer(supplier).data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    list=extend_schema(tags=["Purchasing"], summary="List purchase orders"),
    retrieve=extend_schema(tags=["Purchasing"], summary="Retrieve purchase order"),
)
class PurchaseOrderViewSet(TenantScopedModelViewSet):
    """API endpoint for Purchase Orders."""

    queryset = (
        PurchaseOrder.all_tenants.all()
        .select_related("supplier", "branch", "warehouse")
        .prefetch_related("lines__product")
    )
    serializer_class = PurchaseOrderSerializer
    lookup_field = "public_id"
    required_permission = "purchasing.view"
    search_fields = ["order_number", "supplier__name", "supplier__code"]
    ordering_fields = ["order_date", "grand_total", "created_at"]
    ordering = ["-order_date", "-id"]

    @extend_schema(
        tags=["Purchasing"],
        summary="Create purchase order",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        request=PurchaseOrderCreateSerializer,
        responses={201: PurchaseOrderSerializer},
    )
    @idempotent
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = PurchaseOrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        po = services.create_purchase_order(
            organization=self.get_tenant(),
            supplier=data["supplier"],
            branch=data.get("branch"),
            warehouse=data.get("warehouse"),
            order_date=data.get("order_date"),
            expected_date=data.get("expected_date"),
            currency=data.get("currency", "USD"),
            lines=data["lines"],
            notes=data.get("notes", ""),
            terms=data.get("terms", ""),
            actor=request.user,
        )
        return Response(PurchaseOrderSerializer(po).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=["Purchasing"],
        summary="Submit purchase order",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        responses={200: PurchaseOrderSerializer},
    )
    @idempotent
    @action(detail=True, methods=["post"], url_path="submit")
    def submit_po(self, request: Request, public_id: str | None = None) -> Response:
        po = self.get_object()
        updated = services.submit_purchase_order(
            organization=self.get_tenant(), purchase_order=po, actor=request.user
        )
        return Response(PurchaseOrderSerializer(updated).data)

    @extend_schema(
        tags=["Purchasing"],
        summary="Approve purchase order",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        responses={200: PurchaseOrderSerializer},
    )
    @idempotent
    @action(detail=True, methods=["post"], url_path="approve")
    def approve_po(self, request: Request, public_id: str | None = None) -> Response:
        po = self.get_object()
        updated = services.approve_purchase_order(
            organization=self.get_tenant(), purchase_order=po, actor=request.user
        )
        return Response(PurchaseOrderSerializer(updated).data)

    @extend_schema(
        tags=["Purchasing"],
        summary="Cancel purchase order",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        responses={200: PurchaseOrderSerializer},
    )
    @idempotent
    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel_po(self, request: Request, public_id: str | None = None) -> Response:
        po = self.get_object()
        updated = services.cancel_purchase_order(
            organization=self.get_tenant(), purchase_order=po, actor=request.user
        )
        return Response(PurchaseOrderSerializer(updated).data)


@extend_schema_view(
    list=extend_schema(tags=["Purchasing"], summary="List goods receipts"),
    retrieve=extend_schema(tags=["Purchasing"], summary="Retrieve goods receipt"),
)
class GoodsReceiptViewSet(TenantScopedModelViewSet):
    """API endpoint for Goods Receipts."""

    queryset = (
        GoodsReceipt.all_tenants.all()
        .select_related("supplier", "warehouse", "purchase_order")
        .prefetch_related("lines__product")
    )
    serializer_class = GoodsReceiptSerializer
    lookup_field = "public_id"
    required_permission = "purchasing.view"
    search_fields = ["receipt_number", "supplier__name"]
    ordering_fields = ["date", "total_cost", "created_at"]
    ordering = ["-date", "-id"]

    @extend_schema(
        tags=["Purchasing"],
        summary="Create goods receipt",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        request=GoodsReceiptCreateSerializer,
        responses={201: GoodsReceiptSerializer},
    )
    @idempotent
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = GoodsReceiptCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        receipt = services.create_goods_receipt(
            organization=self.get_tenant(),
            supplier=data["supplier"],
            warehouse=data["warehouse"],
            purchase_order=data.get("purchase_order"),
            date=data.get("date"),
            lines=data["lines"],
            notes=data.get("notes", ""),
            actor=request.user,
        )
        return Response(GoodsReceiptSerializer(receipt).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=["Purchasing"],
        summary="Confirm goods receipt into inventory",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        responses={200: GoodsReceiptSerializer},
    )
    @idempotent
    @action(detail=True, methods=["post"], url_path="receive")
    def receive_stock(self, request: Request, public_id: str | None = None) -> Response:
        receipt = self.get_object()
        updated = services.receive_goods_receipt(
            organization=self.get_tenant(), goods_receipt=receipt, actor=request.user
        )
        return Response(GoodsReceiptSerializer(updated).data)


@extend_schema_view(
    list=extend_schema(tags=["Purchasing"], summary="List supplier bills"),
    retrieve=extend_schema(tags=["Purchasing"], summary="Retrieve supplier bill"),
)
class SupplierBillViewSet(TenantScopedModelViewSet):
    """API endpoint for Supplier Bills."""

    queryset = (
        SupplierBill.all_tenants.all()
        .select_related("supplier", "purchase_order", "goods_receipt")
        .prefetch_related("lines__product")
    )
    serializer_class = SupplierBillSerializer
    lookup_field = "public_id"
    required_permission = "purchasing.view"
    search_fields = ["bill_number", "supplier_reference", "supplier__name"]
    ordering_fields = ["issue_date", "due_date", "total_amount", "balance_due"]
    ordering = ["-issue_date", "-id"]

    @extend_schema(
        tags=["Purchasing"],
        summary="Create supplier bill",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        request=SupplierBillCreateSerializer,
        responses={201: SupplierBillSerializer},
    )
    @idempotent
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = SupplierBillCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        bill = services.create_supplier_bill(
            organization=self.get_tenant(),
            supplier=data["supplier"],
            due_date=data["due_date"],
            issue_date=data.get("issue_date"),
            supplier_reference=data.get("supplier_reference", ""),
            purchase_order=data.get("purchase_order"),
            goods_receipt=data.get("goods_receipt"),
            currency=data.get("currency", "USD"),
            lines=data["lines"],
            notes=data.get("notes", ""),
            actor=request.user,
        )
        return Response(SupplierBillSerializer(bill).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=["Purchasing"],
        summary="Post supplier bill to general ledger",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        responses={200: SupplierBillSerializer},
    )
    @idempotent
    @action(detail=True, methods=["post"], url_path="post")
    def post_bill(self, request: Request, public_id: str | None = None) -> Response:
        bill = self.get_object()
        updated = services.post_supplier_bill(organization=self.get_tenant(), bill=bill, actor=request.user)
        return Response(SupplierBillSerializer(updated).data)

    @extend_schema(
        tags=["Purchasing"],
        summary="Void supplier bill and reverse ledger entries",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        responses={200: SupplierBillSerializer},
    )
    @idempotent
    @action(detail=True, methods=["post"], url_path="void")
    def void_bill(self, request: Request, public_id: str | None = None) -> Response:
        bill = self.get_object()
        updated = services.void_supplier_bill(organization=self.get_tenant(), bill=bill, actor=request.user)
        return Response(SupplierBillSerializer(updated).data)


@extend_schema_view(
    list=extend_schema(tags=["Purchasing"], summary="List supplier payments"),
    retrieve=extend_schema(tags=["Purchasing"], summary="Retrieve supplier payment"),
)
class SupplierPaymentViewSet(TenantScopedModelViewSet):
    """API endpoint for Supplier Payments."""

    queryset = (
        SupplierPayment.all_tenants.all().select_related("supplier").prefetch_related("allocations__bill")
    )
    serializer_class = SupplierPaymentSerializer
    lookup_field = "public_id"
    required_permission = "purchasing.view"
    search_fields = ["payment_number", "reference", "supplier__name"]
    ordering_fields = ["payment_date", "amount", "created_at"]
    ordering = ["-payment_date", "-id"]

    @extend_schema(
        tags=["Purchasing"],
        summary="Record and allocate supplier payment",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        request=SupplierPaymentCreateSerializer,
        responses={201: SupplierPaymentSerializer},
    )
    @idempotent
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = SupplierPaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        payment = services.record_supplier_payment(
            organization=self.get_tenant(),
            supplier=data["supplier"],
            amount=data["amount"],
            payment_method=data.get("payment_method", "bank_transfer"),
            payment_date=data.get("payment_date"),
            reference=data.get("reference", ""),
            allocations=data.get("allocations"),
            notes=data.get("notes", ""),
            actor=request.user,
        )
        return Response(SupplierPaymentSerializer(payment).data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    list=extend_schema(tags=["Purchasing"], summary="List purchase returns"),
    retrieve=extend_schema(tags=["Purchasing"], summary="Retrieve purchase return"),
)
class PurchaseReturnViewSet(TenantScopedModelViewSet):
    """API endpoint for Purchase Returns."""

    queryset = (
        PurchaseReturn.all_tenants.all()
        .select_related("supplier", "warehouse", "goods_receipt", "bill")
        .prefetch_related("lines__product")
    )
    serializer_class = PurchaseReturnSerializer
    lookup_field = "public_id"
    required_permission = "purchasing.view"
    search_fields = ["return_number", "supplier__name"]
    ordering_fields = ["return_date", "total_amount", "created_at"]
    ordering = ["-return_date", "-id"]

    @extend_schema(
        tags=["Purchasing"],
        summary="Create purchase return",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        request=PurchaseReturnCreateSerializer,
        responses={201: PurchaseReturnSerializer},
    )
    @idempotent
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = PurchaseReturnCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        ret = services.create_purchase_return(
            organization=self.get_tenant(),
            supplier=data["supplier"],
            warehouse=data["warehouse"],
            goods_receipt=data.get("goods_receipt"),
            bill=data.get("bill"),
            return_date=data.get("return_date"),
            lines=data["lines"],
            reason=data.get("reason", ""),
            actor=request.user,
        )
        return Response(PurchaseReturnSerializer(ret).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=["Purchasing"],
        summary="Post purchase return to inventory and ledger",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        responses={200: PurchaseReturnSerializer},
    )
    @idempotent
    @action(detail=True, methods=["post"], url_path="post")
    def post_return(self, request: Request, public_id: str | None = None) -> Response:
        ret = self.get_object()
        updated = services.post_purchase_return(
            organization=self.get_tenant(), purchase_return=ret, actor=request.user
        )
        return Response(PurchaseReturnSerializer(updated).data)
