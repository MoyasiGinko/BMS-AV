from typing import Any

from django.db.models import QuerySet
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api.viewsets import TenantScopedModelViewSet
from apps.sales import services
from apps.sales.api.serializers import (
    CreditNoteCreateSerializer,
    CreditNoteSerializer,
    InvoiceCreateSerializer,
    InvoiceSerializer,
    PaymentAllocateActionSerializer,
    PaymentCreateSerializer,
    PaymentRefundActionSerializer,
    PaymentSerializer,
    PaymentVoidActionSerializer,
    QuoteCreateSerializer,
    QuoteSerializer,
    SalesOrderCreateSerializer,
    SalesOrderSerializer,
)
from apps.sales.exceptions import SalesError
from apps.sales.models import CreditNote, Invoice, Payment, Quote, SalesOrder


class QuoteViewSet(TenantScopedModelViewSet):
    """API endpoint for managing sales quotations."""

    queryset = Quote.all_tenants.all()
    serializer_class = QuoteSerializer
    lookup_field = "public_id"
    required_permission = "sales.view"
    search_fields = ["quote_number", "customer__name", "customer__code"]
    ordering_fields = ["date", "grand_total", "created_at"]
    ordering = ["-date", "-id"]

    def get_queryset(self) -> QuerySet[Quote]:
        org = self.get_tenant()
        return (
            Quote.all_tenants.filter(organization=org)
            .select_related("customer", "branch")
            .prefetch_related("lines__product", "lines__variant")
        )

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = QuoteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            quote = serializer.save(
                organization=self.get_tenant(),
                created_by=request.user,
            )
            return Response(QuoteSerializer(quote).data, status=status.HTTP_201_CREATED)
        except SalesError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def accept(self, request: Request, public_id: str | None = None) -> Response:
        quote = self.get_object()
        try:
            quote = services.accept_quote(
                organization=self.get_tenant(),
                quote=quote,
                actor=request.user,
            )
            return Response(QuoteSerializer(quote).data)
        except SalesError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def convert(self, request: Request, public_id: str | None = None) -> Response:
        quote = self.get_object()
        try:
            order = services.convert_quote_to_order(
                organization=self.get_tenant(),
                quote=quote,
                actor=request.user,
            )
            return Response(SalesOrderSerializer(order).data, status=status.HTTP_201_CREATED)
        except SalesError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class SalesOrderViewSet(TenantScopedModelViewSet):
    """API endpoint for managing sales orders."""

    queryset = SalesOrder.all_tenants.all()
    serializer_class = SalesOrderSerializer
    lookup_field = "public_id"
    required_permission = "sales.view"
    search_fields = ["order_number", "customer__name", "customer__code"]
    ordering_fields = ["order_date", "grand_total", "created_at"]
    ordering = ["-order_date", "-id"]

    def get_queryset(self) -> QuerySet[SalesOrder]:
        org = self.get_tenant()
        return (
            SalesOrder.all_tenants.filter(organization=org)
            .select_related("customer", "branch", "warehouse", "quote")
            .prefetch_related("lines__product", "lines__variant")
        )

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = SalesOrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            order = serializer.save(
                organization=self.get_tenant(),
                created_by=request.user,
            )
            return Response(SalesOrderSerializer(order).data, status=status.HTTP_201_CREATED)
        except SalesError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def confirm(self, request: Request, public_id: str | None = None) -> Response:
        order = self.get_object()
        try:
            order = services.confirm_sales_order(
                organization=self.get_tenant(),
                order=order,
                actor=request.user,
            )
            return Response(SalesOrderSerializer(order).data)
        except SalesError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, public_id: str | None = None) -> Response:
        order = self.get_object()
        try:
            order = services.cancel_sales_order(
                organization=self.get_tenant(),
                order=order,
                actor=request.user,
            )
            return Response(SalesOrderSerializer(order).data)
        except SalesError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def convert_to_invoice(self, request: Request, public_id: str | None = None) -> Response:
        order = self.get_object()
        try:
            invoice = services.convert_order_to_invoice(
                organization=self.get_tenant(),
                order=order,
                actor=request.user,
            )
            return Response(InvoiceSerializer(invoice).data, status=status.HTTP_201_CREATED)
        except SalesError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class InvoiceViewSet(TenantScopedModelViewSet):
    """API endpoint for managing sales invoices and posting to ledger."""

    queryset = Invoice.all_tenants.all()
    serializer_class = InvoiceSerializer
    lookup_field = "public_id"
    required_permission = "sales.view"
    search_fields = ["invoice_number", "customer__name", "customer__code"]
    ordering_fields = ["invoice_date", "grand_total", "balance_due", "created_at"]
    ordering = ["-invoice_date", "-id"]

    def get_queryset(self) -> QuerySet[Invoice]:
        org = self.get_tenant()
        return (
            Invoice.all_tenants.filter(organization=org)
            .select_related("customer", "branch", "warehouse", "order", "journal_entry")
            .prefetch_related("lines__product", "lines__variant")
        )

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = InvoiceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            invoice = serializer.save(
                organization=self.get_tenant(),
                created_by=request.user,
            )
            return Response(InvoiceSerializer(invoice).data, status=status.HTTP_201_CREATED)
        except SalesError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"], url_path="post")
    def post_invoice(self, request: Request, public_id: str | None = None) -> Response:
        invoice = self.get_object()
        try:
            invoice = services.post_invoice(
                organization=self.get_tenant(),
                invoice=invoice,
                actor=request.user,
            )
            return Response(InvoiceSerializer(invoice).data)
        except SalesError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def void(self, request: Request, public_id: str | None = None) -> Response:
        invoice = self.get_object()
        data = request.data if isinstance(request.data, dict) else {}
        reason = str(data.get("reason", "Voided via API"))
        try:
            invoice = services.void_invoice(
                organization=self.get_tenant(),
                invoice=invoice,
                actor=request.user,
                reason=reason,
            )
            return Response(InvoiceSerializer(invoice).data)
        except SalesError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class CreditNoteViewSet(TenantScopedModelViewSet):
    """API endpoint for managing sales credit notes and returns."""

    queryset = CreditNote.all_tenants.all()
    serializer_class = CreditNoteSerializer
    lookup_field = "public_id"
    required_permission = "sales.view"
    search_fields = ["credit_note_number", "customer__name", "customer__code"]
    ordering_fields = ["credit_note_date", "grand_total", "created_at"]
    ordering = ["-credit_note_date", "-id"]

    def get_queryset(self) -> QuerySet[CreditNote]:
        org = self.get_tenant()
        return (
            CreditNote.all_tenants.filter(organization=org)
            .select_related("customer", "branch", "warehouse", "invoice", "journal_entry")
            .prefetch_related("lines__product", "lines__variant")
        )

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = CreditNoteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            credit_note = serializer.save(
                organization=self.get_tenant(),
                created_by=request.user,
            )
            return Response(CreditNoteSerializer(credit_note).data, status=status.HTTP_201_CREATED)
        except SalesError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"], url_path="post")
    def post_credit_note(self, request: Request, public_id: str | None = None) -> Response:
        credit_note = self.get_object()
        try:
            credit_note = services.post_credit_note(
                organization=self.get_tenant(),
                credit_note=credit_note,
                actor=request.user,
            )
            return Response(CreditNoteSerializer(credit_note).data)
        except SalesError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class PaymentViewSet(TenantScopedModelViewSet):
    """API endpoint for managing customer payments and allocations."""

    queryset = Payment.all_tenants.all()
    serializer_class = PaymentSerializer
    lookup_field = "public_id"
    required_permission = "sales.view"
    filterset_fields = ["status", "payment_method", "customer"]
    search_fields = ["payment_number", "customer__name", "customer__code", "reference"]
    ordering_fields = ["payment_date", "amount", "created_at"]
    ordering = ["-payment_date", "-id"]

    def get_queryset(self) -> QuerySet[Payment]:
        org = self.get_tenant()
        return (
            Payment.all_tenants.filter(organization=org)
            .select_related("customer", "branch")
            .prefetch_related("allocations__invoice", "refunds")
        )

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = PaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payment = serializer.save(
                organization=self.get_tenant(),
                created_by=request.user,
            )
            return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)
        except SalesError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def allocate(self, request: Request, public_id: str | None = None) -> Response:
        payment = self.get_object()
        serializer = PaymentAllocateActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        raw_allocations = serializer.validated_data["allocations"]
        allocations = [
            {"invoice_id": item["invoice"].pk, "amount": item["amount"]} for item in raw_allocations
        ]

        try:
            payment = services.allocate_payment(
                organization=self.get_tenant(),
                payment=payment,
                allocations=allocations,
                actor=request.user,
            )
            return Response(PaymentSerializer(payment).data)
        except SalesError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def refund(self, request: Request, public_id: str | None = None) -> Response:
        payment = self.get_object()
        serializer = PaymentRefundActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            services.refund_payment(
                organization=self.get_tenant(),
                payment=payment,
                amount=serializer.validated_data["amount"],
                refund_date=serializer.validated_data.get("refund_date"),
                reason=serializer.validated_data.get("reason", ""),
                actor=request.user,
            )
            payment.refresh_from_db()
            return Response(PaymentSerializer(payment).data)
        except SalesError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def void(self, request: Request, public_id: str | None = None) -> Response:
        payment = self.get_object()
        serializer = PaymentVoidActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            payment = services.void_payment(
                organization=self.get_tenant(),
                payment=payment,
                reason=serializer.validated_data.get("reason", ""),
                actor=request.user,
            )
            return Response(PaymentSerializer(payment).data)
        except SalesError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
