from typing import Any

from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api.idempotency import IDEMPOTENCY_KEY_PARAMETER, idempotent
from apps.core.api.viewsets import TenantScopedModelViewSet
from apps.sales import services
from apps.sales.api.serializers import (
    CreditNoteCreateSerializer,
    CreditNoteSerializer,
    InvoiceCreateSerializer,
    InvoiceSerializer,
    InvoiceVoidActionSerializer,
    PaymentAllocateActionSerializer,
    PaymentCreateSerializer,
    PaymentRefundActionSerializer,
    PaymentReminderLogSerializer,
    PaymentReminderRuleSerializer,
    PaymentSerializer,
    PaymentVoidActionSerializer,
    QuoteCreateSerializer,
    QuoteSerializer,
    RecurringInvoiceProfileCreateSerializer,
    RecurringInvoiceProfileSerializer,
    SalesOrderCreateSerializer,
    SalesOrderSerializer,
)
from apps.sales.exceptions import PaymentReminderError, RecurringProfileError, SalesError
from apps.sales.models import (
    CreditNote,
    Invoice,
    Payment,
    PaymentReminderLog,
    PaymentReminderRule,
    Quote,
    RecurringInvoiceProfile,
    SalesOrder,
)


@extend_schema_view(
    list=extend_schema(tags=["Sales"], summary="List sales quotes"),
    retrieve=extend_schema(tags=["Sales"], summary="Retrieve sales quote"),
    update=extend_schema(tags=["Sales"], summary="Update sales quote"),
    partial_update=extend_schema(tags=["Sales"], summary="Partially update sales quote"),
    destroy=extend_schema(tags=["Sales"], summary="Delete sales quote"),
)
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

    @extend_schema(
        tags=["Sales"],
        summary="Create sales quote",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        request=QuoteCreateSerializer,
        responses={201: QuoteSerializer, 400: OpenApiResponse(description="Sales error")},
    )
    @idempotent
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

    @extend_schema(
        tags=["Sales"],
        summary="Accept sales quote",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        request=None,
        responses={200: QuoteSerializer, 400: OpenApiResponse(description="Sales error")},
    )
    @action(detail=True, methods=["post"])
    @idempotent
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

    @extend_schema(
        tags=["Sales"],
        summary="Convert sales quote to sales order",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        request=None,
        responses={201: SalesOrderSerializer, 400: OpenApiResponse(description="Sales error")},
    )
    @action(detail=True, methods=["post"])
    @idempotent
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


@extend_schema_view(
    list=extend_schema(tags=["Sales"], summary="List sales orders"),
    retrieve=extend_schema(tags=["Sales"], summary="Retrieve sales order"),
    update=extend_schema(tags=["Sales"], summary="Update sales order"),
    partial_update=extend_schema(tags=["Sales"], summary="Partially update sales order"),
    destroy=extend_schema(tags=["Sales"], summary="Delete sales order"),
)
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

    @extend_schema(
        tags=["Sales"],
        summary="Create sales order",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        request=SalesOrderCreateSerializer,
        responses={201: SalesOrderSerializer, 400: OpenApiResponse(description="Sales error")},
    )
    @idempotent
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

    @extend_schema(
        tags=["Sales"],
        summary="Confirm sales order and allocate inventory",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        request=None,
        responses={200: SalesOrderSerializer, 400: OpenApiResponse(description="Sales error")},
    )
    @action(detail=True, methods=["post"])
    @idempotent
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

    @extend_schema(
        tags=["Sales"],
        summary="Cancel sales order and release stock",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        request=None,
        responses={200: SalesOrderSerializer, 400: OpenApiResponse(description="Sales error")},
    )
    @action(detail=True, methods=["post"])
    @idempotent
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

    @extend_schema(
        tags=["Sales"],
        summary="Convert sales order to invoice",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        request=None,
        responses={201: InvoiceSerializer, 400: OpenApiResponse(description="Sales error")},
    )
    @action(detail=True, methods=["post"])
    @idempotent
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


@extend_schema_view(
    list=extend_schema(tags=["Sales"], summary="List sales invoices"),
    retrieve=extend_schema(tags=["Sales"], summary="Retrieve sales invoice"),
    update=extend_schema(tags=["Sales"], summary="Update sales invoice"),
    partial_update=extend_schema(tags=["Sales"], summary="Partially update sales invoice"),
    destroy=extend_schema(tags=["Sales"], summary="Delete draft sales invoice"),
)
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

    @extend_schema(
        tags=["Sales"],
        summary="Create draft sales invoice",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        request=InvoiceCreateSerializer,
        responses={201: InvoiceSerializer, 400: OpenApiResponse(description="Sales error")},
    )
    @idempotent
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

    @extend_schema(
        tags=["Sales"],
        summary="Post sales invoice to general ledger and AR",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        request=None,
        responses={200: InvoiceSerializer, 400: OpenApiResponse(description="Sales error")},
    )
    @action(detail=True, methods=["post"], url_path="post")
    @idempotent
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

    @extend_schema(
        tags=["Sales"],
        summary="Void sales invoice and reverse ledger postings",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        request=InvoiceVoidActionSerializer,
        responses={200: InvoiceSerializer, 400: OpenApiResponse(description="Sales error")},
    )
    @action(detail=True, methods=["post"])
    @idempotent
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


@extend_schema_view(
    list=extend_schema(tags=["Sales"], summary="List credit notes"),
    retrieve=extend_schema(tags=["Sales"], summary="Retrieve credit note"),
    update=extend_schema(tags=["Sales"], summary="Update credit note"),
    partial_update=extend_schema(tags=["Sales"], summary="Partially update credit note"),
    destroy=extend_schema(tags=["Sales"], summary="Delete draft credit note"),
)
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

    @extend_schema(
        tags=["Sales"],
        summary="Create draft credit note",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        request=CreditNoteCreateSerializer,
        responses={201: CreditNoteSerializer, 400: OpenApiResponse(description="Sales error")},
    )
    @idempotent
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

    @extend_schema(
        tags=["Sales"],
        summary="Post credit note to general ledger",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        request=None,
        responses={200: CreditNoteSerializer, 400: OpenApiResponse(description="Sales error")},
    )
    @action(detail=True, methods=["post"], url_path="post")
    @idempotent
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


@extend_schema_view(
    list=extend_schema(tags=["Sales"], summary="List customer payments"),
    retrieve=extend_schema(tags=["Sales"], summary="Retrieve customer payment"),
    update=extend_schema(tags=["Sales"], summary="Update customer payment"),
    partial_update=extend_schema(tags=["Sales"], summary="Partially update customer payment"),
    destroy=extend_schema(tags=["Sales"], summary="Delete customer payment"),
)
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

    @extend_schema(
        tags=["Sales"],
        summary="Record customer payment",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        request=PaymentCreateSerializer,
        responses={201: PaymentSerializer, 400: OpenApiResponse(description="Sales error")},
    )
    @idempotent
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

    @extend_schema(
        tags=["Sales"],
        summary="Allocate payment against open invoices",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        request=PaymentAllocateActionSerializer,
        responses={200: PaymentSerializer, 400: OpenApiResponse(description="Sales error")},
    )
    @action(detail=True, methods=["post"])
    @idempotent
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

    @extend_schema(
        tags=["Sales"],
        summary="Refund customer payment",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        request=PaymentRefundActionSerializer,
        responses={200: PaymentSerializer, 400: OpenApiResponse(description="Sales error")},
    )
    @action(detail=True, methods=["post"])
    @idempotent
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

    @extend_schema(
        tags=["Sales"],
        summary="Void unallocated customer payment",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        request=PaymentVoidActionSerializer,
        responses={200: PaymentSerializer, 400: OpenApiResponse(description="Sales error")},
    )
    @action(detail=True, methods=["post"])
    @idempotent
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


# ============================================================================
# RECURRING INVOICE PROFILE VIEWSET
# ============================================================================


@extend_schema_view(
    list=extend_schema(tags=["Sales"], summary="List recurring invoice profiles"),
    retrieve=extend_schema(tags=["Sales"], summary="Retrieve recurring invoice profile"),
    update=extend_schema(tags=["Sales"], summary="Update recurring invoice profile"),
    partial_update=extend_schema(tags=["Sales"], summary="Partially update recurring invoice profile"),
    destroy=extend_schema(tags=["Sales"], summary="Delete recurring invoice profile"),
)
class RecurringInvoiceProfileViewSet(TenantScopedModelViewSet):
    """API endpoint for recurring invoice schedule profiles."""

    queryset = RecurringInvoiceProfile.all_tenants.all()
    serializer_class = RecurringInvoiceProfileSerializer
    lookup_field = "public_id"
    required_permission = "sales.view"
    search_fields = ["title", "customer__name", "customer__code"]
    ordering_fields = ["next_issue_date", "start_date", "created_at"]
    ordering = ["next_issue_date", "-id"]

    def get_queryset(self) -> QuerySet[RecurringInvoiceProfile]:
        org = self.get_tenant()
        return (
            RecurringInvoiceProfile.all_tenants.filter(organization=org)
            .select_related("customer", "warehouse", "branch")
            .prefetch_related("lines__product", "lines__variant")
        )

    @extend_schema(
        tags=["Sales"],
        summary="Create recurring invoice profile",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        request=RecurringInvoiceProfileCreateSerializer,
        responses={
            201: RecurringInvoiceProfileSerializer,
            400: OpenApiResponse(description="Validation error"),
        },
    )
    @idempotent
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = RecurringInvoiceProfileCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            profile = serializer.save(
                organization=self.get_tenant(),
                created_by=request.user,
            )
            return Response(RecurringInvoiceProfileSerializer(profile).data, status=status.HTTP_201_CREATED)
        except (RecurringProfileError, SalesError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=["Sales"],
        operation_id="sales_recurring_invoice_pause",
        summary="Pause recurring invoice profile",
        request=None,
        responses={200: RecurringInvoiceProfileSerializer, 400: OpenApiResponse(description="Error")},
    )
    @action(detail=True, methods=["post"])
    def pause(self, request: Request, public_id: str | None = None) -> Response:
        profile = self.get_object()
        try:
            profile = services.pause_recurring_profile(
                organization=self.get_tenant(),
                profile=profile,
                actor=request.user,
            )
            return Response(RecurringInvoiceProfileSerializer(profile).data)
        except (RecurringProfileError, SalesError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=["Sales"],
        operation_id="sales_recurring_invoice_resume",
        summary="Resume paused recurring invoice profile",
        request=None,
        responses={200: RecurringInvoiceProfileSerializer, 400: OpenApiResponse(description="Error")},
    )
    @action(detail=True, methods=["post"])
    def resume(self, request: Request, public_id: str | None = None) -> Response:
        profile = self.get_object()
        try:
            profile = services.resume_recurring_profile(
                organization=self.get_tenant(),
                profile=profile,
                actor=request.user,
            )
            return Response(RecurringInvoiceProfileSerializer(profile).data)
        except (RecurringProfileError, SalesError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=["Sales"],
        operation_id="sales_recurring_invoice_cancel",
        summary="Cancel recurring invoice profile",
        request=None,
        responses={200: RecurringInvoiceProfileSerializer, 400: OpenApiResponse(description="Error")},
    )
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, public_id: str | None = None) -> Response:
        profile = self.get_object()
        try:
            profile = services.cancel_recurring_profile(
                organization=self.get_tenant(),
                profile=profile,
                actor=request.user,
            )
            return Response(RecurringInvoiceProfileSerializer(profile).data)
        except (RecurringProfileError, SalesError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=["Sales"],
        operation_id="sales_recurring_invoice_generate_now",
        summary="Immediately generate an invoice for this recurring profile",
        request=None,
        responses={201: InvoiceSerializer, 400: OpenApiResponse(description="Error")},
    )
    @action(detail=True, methods=["post"])
    def generate_now(self, request: Request, public_id: str | None = None) -> Response:
        profile = self.get_object()
        try:
            invoice = services.generate_single_recurring_invoice(
                organization=self.get_tenant(),
                profile=profile,
                actor=request.user,
            )
            return Response(InvoiceSerializer(invoice).data, status=status.HTTP_201_CREATED)
        except (RecurringProfileError, SalesError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


# ============================================================================
# PAYMENT REMINDER RULE & LOG VIEWSETS
# ============================================================================


@extend_schema_view(
    list=extend_schema(tags=["Sales"], summary="List payment reminder rules"),
    retrieve=extend_schema(tags=["Sales"], summary="Retrieve payment reminder rule"),
    update=extend_schema(tags=["Sales"], summary="Update payment reminder rule"),
    partial_update=extend_schema(tags=["Sales"], summary="Partially update payment reminder rule"),
    destroy=extend_schema(tags=["Sales"], summary="Delete payment reminder rule"),
)
class PaymentReminderRuleViewSet(TenantScopedModelViewSet):
    """API endpoint for configuring invoice payment reminder rules."""

    queryset = PaymentReminderRule.all_tenants.all()
    serializer_class = PaymentReminderRuleSerializer
    lookup_field = "public_id"
    required_permission = "sales.view"
    search_fields = ["name"]
    ordering_fields = ["timing_days", "name"]
    ordering = ["timing_days"]

    def get_queryset(self) -> QuerySet[PaymentReminderRule]:
        org = self.get_tenant()
        return PaymentReminderRule.all_tenants.filter(organization=org)

    @extend_schema(
        tags=["Sales"],
        summary="Create payment reminder rule",
        request=PaymentReminderRuleSerializer,
        responses={201: PaymentReminderRuleSerializer, 400: OpenApiResponse(description="Error")},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            rule = services.create_payment_reminder_rule(
                organization=self.get_tenant(),
                name=serializer.validated_data["name"],
                timing_days=serializer.validated_data["timing_days"],
                is_active=serializer.validated_data.get("is_active", True),
                subject_template=serializer.validated_data.get(
                    "subject_template",
                    "Payment Reminder: Invoice {{ invoice_number }} from {{ org_name }}",
                ),
                body_template=serializer.validated_data.get(
                    "body_template",
                    "Dear {{ customer_name }},\n\nPayment Reminder for Invoice {{ invoice_number }}.",
                ),
                actor=request.user,
            )
            return Response(PaymentReminderRuleSerializer(rule).data, status=status.HTTP_201_CREATED)
        except (PaymentReminderError, SalesError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    def perform_destroy(self, instance: PaymentReminderRule) -> None:
        services.delete_payment_reminder_rule(
            organization=self.get_tenant(),
            rule=instance,
            actor=self.request.user,
        )


@extend_schema_view(
    list=extend_schema(tags=["Sales"], summary="List payment reminder audit logs"),
    retrieve=extend_schema(tags=["Sales"], summary="Retrieve payment reminder audit log"),
)
class PaymentReminderLogViewSet(TenantScopedModelViewSet):
    """API endpoint for viewing payment reminder delivery logs and manually triggering reminders."""

    queryset = PaymentReminderLog.all_tenants.all()
    serializer_class = PaymentReminderLogSerializer
    lookup_field = "public_id"
    required_permission = "sales.view"
    http_method_names = ["get", "post", "head", "options"]
    search_fields = ["invoice__invoice_number", "recipient_email"]
    ordering_fields = ["sent_at", "timing_days"]
    ordering = ["-sent_at"]

    def get_queryset(self) -> QuerySet[PaymentReminderLog]:
        org = self.get_tenant()
        return PaymentReminderLog.all_tenants.filter(organization=org).select_related("invoice", "rule")

    @extend_schema(
        tags=["Sales"],
        operation_id="sales_payment_reminders_dispatch_now",
        summary="Trigger immediate processing of due payment reminders",
        request=None,
        responses={200: OpenApiResponse(description="Summary of dispatched reminders")},
    )
    @action(detail=False, methods=["post"])
    def dispatch_now(self, request: Request) -> Response:
        try:
            results = services.process_due_payment_reminders(
                organization=self.get_tenant(),
                actor=request.user,
            )
            return Response(
                {
                    "detail": "Payment reminders processed successfully.",
                    "sent_count": len(results.get("sent", [])),
                    "skipped_count": len(results.get("skipped", [])),
                    "failed_count": len(results.get("failed", [])),
                    "sent": results.get("sent", []),
                    "skipped": results.get("skipped", []),
                    "failed": results.get("failed", []),
                },
                status=status.HTTP_200_OK,
            )
        except (PaymentReminderError, SalesError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
