"""DRF API ViewSets for customer resources and statements."""

from __future__ import annotations

import datetime
from typing import Any

from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from apps.core.api.idempotency import IDEMPOTENCY_KEY_PARAMETER, idempotent
from apps.core.api.viewsets import TenantScopedModelViewSet
from apps.customers import selectors, services
from apps.customers.api.serializers import (
    CustomerAddressSerializer,
    CustomerAdjustmentInputSerializer,
    CustomerBalanceEntrySerializer,
    CustomerContactSerializer,
    CustomerCreateSerializer,
    CustomerDetailSerializer,
    CustomerSerializer,
)
from apps.customers.exceptions import CreditLimitExceeded, CustomerError
from apps.customers.models import (
    Customer,
    CustomerAddress,
    CustomerBalanceEntry,
    CustomerContact,
)


@extend_schema_view(
    list=extend_schema(tags=["Customers"], summary="List customer accounts"),
    retrieve=extend_schema(tags=["Customers"], summary="Retrieve customer account detail"),
    create=extend_schema(tags=["Customers"], summary="Create customer account"),
    update=extend_schema(tags=["Customers"], summary="Update customer account"),
    partial_update=extend_schema(tags=["Customers"], summary="Partially update customer account"),
    destroy=extend_schema(tags=["Customers"], summary="Delete customer account"),
)
class CustomerViewSet(TenantScopedModelViewSet):
    """API endpoint for managing customer accounts, ledgers, and statements."""

    queryset = Customer.objects.select_related("price_list").prefetch_related("addresses", "contacts").all()
    lookup_field = "public_id"
    module_key = "customers"
    permission_map = {
        "list": "customers.view",
        "retrieve": "customers.view",
        "create": "customers.create",
        "update": "customers.update",
        "partial_update": "customers.update",
        "destroy": "customers.delete",
        "ledger": "customers.view",
        "statement": "customers.view",
        "adjust_balance": "customers.adjust_balance",
    }
    search_fields = ["name", "code", "email", "phone", "tax_id"]
    ordering_fields = ["name", "code", "current_balance", "created_at"]
    ordering = ["name"]

    def get_serializer_class(self) -> type[BaseSerializer[Any]]:
        if self.action == "create":
            return CustomerCreateSerializer
        if self.action == "retrieve":
            return CustomerDetailSerializer
        if self.action == "adjust_balance":
            return CustomerAdjustmentInputSerializer
        return CustomerSerializer

    def perform_destroy(self, instance: Customer) -> None:
        org = self.get_tenant()
        services.delete_customer(organization=org, customer=instance, actor=self.request.user)

    @extend_schema(
        tags=["Customers"],
        summary="Retrieve chronological customer accounts receivable ledger",
        responses={200: CustomerBalanceEntrySerializer(many=True)},
    )
    @action(detail=True, methods=["get"], url_path="ledger")
    def ledger(self, request: Request, public_id: str | None = None) -> Response:
        """Retrieve chronological accounts receivable ledger for this customer."""
        customer = self.get_object()
        org = self.get_tenant()

        start_date_str = request.query_params.get("start_date")
        end_date_str = request.query_params.get("end_date")
        start_date = datetime.date.fromisoformat(start_date_str) if start_date_str else None
        end_date = datetime.date.fromisoformat(end_date_str) if end_date_str else None

        qs = selectors.get_customer_balance_ledger(
            organization=org,
            customer=customer,
            start_date=start_date,
            end_date=end_date,
        )
        self.ordering = ["-occurred_at", "-id"]
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = CustomerBalanceEntrySerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = CustomerBalanceEntrySerializer(qs, many=True)
        return Response(serializer.data)

    @extend_schema(
        tags=["Customers"],
        summary="Generate period statement with aging breakdown",
        responses={200: OpenApiResponse(description="Customer account statement with aging analysis")},
    )
    @action(detail=True, methods=["get"], url_path="statement")
    def statement(self, request: Request, public_id: str | None = None) -> Response:
        """Generate period statement with aging breakdown."""
        customer = self.get_object()
        org = self.get_tenant()

        today = timezone.localdate()
        start_date_str = request.query_params.get("start_date")
        end_date_str = request.query_params.get("end_date")

        try:
            start_date = (
                datetime.date.fromisoformat(start_date_str) if start_date_str else today.replace(day=1)
            )
        except ValueError, TypeError:
            start_date = today.replace(day=1)

        try:
            end_date = datetime.date.fromisoformat(end_date_str) if end_date_str else today
        except ValueError, TypeError:
            end_date = today

        data = selectors.get_customer_statement(
            organization=org,
            customer=customer,
            start_date=start_date,
            end_date=end_date,
        )

        lines_output = [
            {
                "entry": CustomerBalanceEntrySerializer(line["entry"]).data,
                "running_balance": str(line["running_balance"]),
            }
            for line in data["lines"]
        ]

        aging_output = {k: str(v) for k, v in data["aging"].items()}

        return Response(
            {
                "customer_code": customer.code,
                "customer_name": customer.name,
                "start_date": data["start_date"].isoformat(),
                "end_date": data["end_date"].isoformat(),
                "opening_balance": str(data["opening_balance"]),
                "total_debits": str(data["total_debits"]),
                "total_credits": str(data["total_credits"]),
                "closing_balance": str(data["closing_balance"]),
                "lines": lines_output,
                "aging": aging_output,
            }
        )

    @extend_schema(
        tags=["Customers"],
        summary="Post manual customer balance adjustment",
        parameters=[IDEMPOTENCY_KEY_PARAMETER],
        request=CustomerAdjustmentInputSerializer,
        responses={201: CustomerBalanceEntrySerializer, 400: OpenApiResponse(description="Customer error")},
    )
    @action(detail=True, methods=["post"], url_path="adjust-balance")
    @idempotent
    def adjust_balance(self, request: Request, public_id: str | None = None) -> Response:
        """Post a manual balance debit or credit adjustment."""
        customer = self.get_object()
        org = self.get_tenant()

        serializer = CustomerAdjustmentInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data

        try:
            entry = services.adjust_customer_balance(
                organization=org,
                customer=customer,
                adjustment_type=vd["adjustment_type"],
                amount=vd["amount"],
                reason=vd["reason"],
                reference_number=vd.get("reference_number", ""),
                actor=request.user,
            )
            return Response(CustomerBalanceEntrySerializer(entry).data, status=status.HTTP_201_CREATED)
        except (CustomerError, CreditLimitExceeded) as err:
            return Response({"detail": str(err)}, status=status.HTTP_400_BAD_REQUEST)


@extend_schema_view(
    list=extend_schema(tags=["Customers"], summary="List customer addresses"),
    retrieve=extend_schema(tags=["Customers"], summary="Retrieve customer address"),
    create=extend_schema(tags=["Customers"], summary="Create customer address"),
    update=extend_schema(tags=["Customers"], summary="Update customer address"),
    partial_update=extend_schema(tags=["Customers"], summary="Partially update customer address"),
    destroy=extend_schema(tags=["Customers"], summary="Delete customer address"),
)
class CustomerAddressViewSet(TenantScopedModelViewSet):
    """API endpoint for managing customer physical, billing, and shipping addresses."""

    queryset = CustomerAddress.objects.select_related("customer").all()
    serializer_class = CustomerAddressSerializer
    lookup_field = "public_id"
    module_key = "customers"
    permission_map = {
        "list": "customers.view",
        "retrieve": "customers.view",
        "create": "customers.update",
        "update": "customers.update",
        "partial_update": "customers.update",
        "destroy": "customers.update",
    }


@extend_schema_view(
    list=extend_schema(tags=["Customers"], summary="List customer contacts"),
    retrieve=extend_schema(tags=["Customers"], summary="Retrieve customer contact"),
    create=extend_schema(tags=["Customers"], summary="Create customer contact"),
    update=extend_schema(tags=["Customers"], summary="Update customer contact"),
    partial_update=extend_schema(tags=["Customers"], summary="Partially update customer contact"),
    destroy=extend_schema(tags=["Customers"], summary="Delete customer contact"),
)
class CustomerContactViewSet(TenantScopedModelViewSet):
    """API endpoint for managing customer contact persons."""

    queryset = CustomerContact.objects.select_related("customer").all()
    serializer_class = CustomerContactSerializer
    lookup_field = "public_id"
    module_key = "customers"
    permission_map = {
        "list": "customers.view",
        "retrieve": "customers.view",
        "create": "customers.update",
        "update": "customers.update",
        "partial_update": "customers.update",
        "destroy": "customers.update",
    }


@extend_schema_view(
    list=extend_schema(tags=["Customers"], summary="List customer ledger entries"),
    retrieve=extend_schema(tags=["Customers"], summary="Retrieve customer ledger entry"),
)
class CustomerBalanceEntryViewSet(TenantScopedModelViewSet):
    """API endpoint for inspecting the immutable customer AR ledger."""

    queryset = CustomerBalanceEntry.objects.select_related("customer").all()
    serializer_class = CustomerBalanceEntrySerializer
    lookup_field = "public_id"
    module_key = "customers"
    permission_map = {
        "list": "customers.view",
        "retrieve": "customers.view",
    }
    http_method_names = ["get", "head", "options"]
    search_fields = ["customer__name", "customer__code", "reference_number", "description"]
    ordering_fields = ["occurred_at", "debit", "credit", "balance_after"]
    ordering = ["-occurred_at", "-id"]
