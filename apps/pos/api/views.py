"""REST API ViewSets for the Point of Sale (POS) module."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db.models import QuerySet
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.catalog.models import Product
from apps.core.api.viewsets import TenantScopedModelViewSet
from apps.customers.models import Customer
from apps.pos import selectors, services
from apps.pos.api.serializers import (
    POSCheckoutSerializer,
    POSCloseShiftSerializer,
    POSHeldCartSerializer,
    POSOpenShiftSerializer,
    POSRegisterCreateSerializer,
    POSRegisterSerializer,
    POSSaleSerializer,
    POSShiftSerializer,
)
from apps.pos.exceptions import POSError
from apps.pos.models import POSHeldCart, POSRegister, POSSale, POSShift


class POSRegisterViewSet(TenantScopedModelViewSet):
    """API endpoint for managing POS registers / terminals."""

    queryset = POSRegister.all_tenants.all()
    serializer_class = POSRegisterSerializer
    lookup_field = "public_id"
    required_permission = "pos.access"
    search_fields = ["name", "code", "branch__name", "warehouse__name"]
    ordering_fields = ["code", "name", "created_at"]
    ordering = ["code"]

    def get_queryset(self) -> QuerySet[POSRegister]:
        org = self.get_tenant()
        return POSRegister.all_tenants.filter(organization=org).select_related("branch", "warehouse")

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        org = self.get_tenant()
        serializer = POSRegisterCreateSerializer(data=request.data, context={"organization": org})
        serializer.is_valid(raise_exception=True)
        try:
            reg = services.create_register(
                organization=org,
                name=serializer.cleaned_data["name"]
                if hasattr(serializer, "cleaned_data")
                else serializer.validated_data["name"],
                branch=serializer.validated_data["branch"],
                warehouse=serializer.validated_data["warehouse"],
                code=serializer.validated_data.get("code") or None,
                receipt_header=serializer.validated_data.get("receipt_header", ""),
                receipt_footer=serializer.validated_data.get("receipt_footer", ""),
                is_active=serializer.validated_data.get("is_active", True),
                actor=request.user,
            )
            return Response(POSRegisterSerializer(reg).data, status=status.HTTP_201_CREATED)
        except POSError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class POSShiftViewSet(TenantScopedModelViewSet):
    """API endpoint for cashier shifts and cash audits."""

    queryset = POSShift.all_tenants.all()
    serializer_class = POSShiftSerializer
    lookup_field = "public_id"
    required_permission = "pos.access"
    search_fields = ["shift_number", "register__code", "cashier__email"]
    ordering_fields = ["opened_at", "closed_at", "shift_number"]
    ordering = ["-opened_at"]

    def get_queryset(self) -> QuerySet[POSShift]:
        org = self.get_tenant()
        return POSShift.all_tenants.filter(organization=org).select_related("register", "cashier")

    @action(detail=False, methods=["get"], url_path="active")
    def active(self, request: Request) -> Response:
        """Retrieve current user's active open shift."""
        org = self.get_tenant()
        active_shift = selectors.get_active_shift_for_user(organization=org, user=request.user)
        if not active_shift:
            return Response({"detail": "No active shift open."}, status=status.HTTP_404_NOT_FOUND)
        return Response(POSShiftSerializer(active_shift).data)

    @action(detail=False, methods=["post"], url_path="open")
    def open_shift(self, request: Request) -> Response:
        """Open a new cashier shift."""
        org = self.get_tenant()
        serializer = POSOpenShiftSerializer(data=request.data, context={"organization": org})
        serializer.is_valid(raise_exception=True)
        try:
            shift = services.open_shift(
                organization=org,
                register=serializer.validated_data["register"],
                cashier=request.user,
                opening_cash=serializer.validated_data["opening_cash"],
                notes=serializer.validated_data.get("notes", ""),
                actor=request.user,
            )
            return Response(POSShiftSerializer(shift).data, status=status.HTTP_201_CREATED)
        except POSError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"], url_path="close")
    def close_shift(self, request: Request, public_id: str | None = None) -> Response:
        """Close an active cashier shift."""
        org = self.get_tenant()
        shift = self.get_object()
        serializer = POSCloseShiftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            closed = services.close_shift(
                organization=org,
                shift=shift,
                closing_cash_counted=serializer.validated_data["closing_cash_counted"],
                notes=serializer.validated_data.get("notes", ""),
                actor=request.user,
            )
            return Response(POSShiftSerializer(closed).data)
        except POSError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class POSSaleViewSet(TenantScopedModelViewSet):
    """API endpoint for POS sales and fast counter checkout."""

    queryset = POSSale.all_tenants.all()
    serializer_class = POSSaleSerializer
    lookup_field = "public_id"
    required_permission = "pos.access"
    search_fields = ["receipt_number", "register__code", "invoice__invoice_number", "customer__name"]
    ordering_fields = ["created_at", "total_amount", "receipt_number"]
    ordering = ["-created_at"]

    def get_queryset(self) -> QuerySet[POSSale]:
        org = self.get_tenant()
        return POSSale.all_tenants.filter(organization=org).select_related(
            "register", "shift", "invoice", "customer"
        )

    @action(detail=False, methods=["post"], url_path="checkout")
    def checkout(self, request: Request) -> Response:
        """Atomic POS checkout."""
        org = self.get_tenant()
        serializer = POSCheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        shift = POSShift.all_tenants.filter(organization=org, pk=data["shift_id"]).first()
        if not shift:
            return Response({"detail": "Shift not found."}, status=status.HTTP_404_NOT_FOUND)

        cart_lines = []
        for line in data["lines"]:
            prod = Product.all_tenants.filter(organization=org, pk=line["product_id"]).first()
            if not prod:
                return Response(
                    {"detail": f"Product id {line['product_id']} not found."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            cart_lines.append(
                {
                    "product": prod,
                    "quantity": line["quantity"],
                    "unit_price": line.get("unit_price", prod.selling_price),
                    "discount_percent": line.get("discount_percent", Decimal("0.00")),
                    "tax_rate": line.get(
                        "tax_rate", prod.tax_code.rate if prod.tax_code else Decimal("0.00")
                    ),
                }
            )

        customer = None
        if data.get("customer_id"):
            customer = Customer.all_tenants.filter(organization=org, pk=data["customer_id"]).first()

        try:
            sale = services.checkout_pos_sale(
                organization=org,
                shift=shift,
                lines=cart_lines,
                payments=data["payments"],
                customer=customer,
                amount_tendered=data.get("amount_tendered"),
                notes=data.get("notes", ""),
                actor=request.user,
            )
            return Response(POSSaleSerializer(sale).data, status=status.HTTP_201_CREATED)
        except POSError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class POSHeldCartViewSet(TenantScopedModelViewSet):
    """API endpoint for parked / held carts."""

    queryset = POSHeldCart.all_tenants.all()
    serializer_class = POSHeldCartSerializer
    lookup_field = "id"
    required_permission = "pos.access"
    ordering = ["-created_at"]

    def get_queryset(self) -> QuerySet[POSHeldCart]:
        org = self.get_tenant()
        return POSHeldCart.all_tenants.filter(organization=org)

    @action(detail=True, methods=["post"], url_path="resume")
    def resume(self, request: Request, id: int | None = None) -> Response:
        """Resume a held cart and remove it from parking list."""
        org = self.get_tenant()
        cart = self.get_object()
        try:
            cart_data = services.resume_cart(
                organization=org,
                held_cart_id=cart.pk,
                actor=request.user,
            )
            return Response({"cart": cart_data})
        except POSError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
