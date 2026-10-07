"""Billing API viewsets."""

from __future__ import annotations

import logging
from typing import Any

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing import services
from apps.billing.api.serializers import (
    CancelSubscriptionSerializer,
    ChangePlanSerializer,
    PlanSerializer,
    SubscriptionInvoiceSerializer,
    SubscriptionSerializer,
    UsageCounterSerializer,
)
from apps.billing.gateway import get_payment_gateway
from apps.billing.models import Plan, Subscription, SubscriptionInvoice, UsageCounter
from apps.core.api.idempotency import idempotent
from apps.core.api.viewsets import TenantScopedReadOnlyModelViewSet, TenantScopedViewSet
from apps.core.exceptions import RecordNotFoundError, ValidationError

logger = logging.getLogger(__name__)


class PlanViewSet(viewsets.ReadOnlyModelViewSet):
    """List and inspect available subscription plans."""

    queryset = (
        Plan.objects.filter(is_active=True).prefetch_related("plan_modules__module").order_by("sort_order")
    )
    serializer_class = PlanSerializer
    lookup_field = "slug"
    permission_classes = [permissions.AllowAny]
    public_endpoint = True


class SubscriptionViewSet(TenantScopedViewSet):
    """Tenant subscription management endpoint."""

    module_key = "billing"
    required_permission = "billing.view"
    permission_map = {
        "list": "billing.view",
        "current": "billing.view",
        "change_plan": "billing.manage",
        "cancel": "billing.manage",
    }
    serializer_class = SubscriptionSerializer
    queryset = Subscription.objects.none()

    def get_queryset(self) -> Any:
        if getattr(self, "swagger_fake_view", False):
            return Subscription.objects.none()
        org = self.get_tenant()
        return Subscription.all_tenants.filter(organization=org).select_related("plan")

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Return the active subscription for the current organization."""
        org = self.get_tenant()
        sub = self.get_queryset().first()
        if sub is None:
            raise RecordNotFoundError(f"No subscription found for organization '{getattr(org, 'name', '')}'.")
        serializer = self.get_serializer(sub)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="current")
    def current(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Alias for retrieving current subscription."""
        return self.list(request, *args, **kwargs)

    @action(detail=False, methods=["post"], url_path="change-plan")
    @idempotent()
    def change_plan(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Upgrade or downgrade current organization's subscription tier."""
        sub = self.get_queryset().first()
        if sub is None:
            raise RecordNotFoundError("Cannot change plan: No active subscription found.")

        serializer = ChangePlanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_plan_slug = serializer.validated_data["new_plan_slug"]

        try:
            target_plan = Plan.objects.get(slug=new_plan_slug, is_active=True)
        except Plan.DoesNotExist:
            raise ValidationError(f"Plan '{new_plan_slug}' does not exist or is inactive.") from None

        updated_sub = services.change_subscription_plan(
            subscription=sub,
            new_plan=target_plan,
            actor=request.user,
        )

        return Response(self.get_serializer(updated_sub).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="cancel")
    @idempotent()
    def cancel(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Cancel subscription immediately or at period end."""
        sub = self.get_queryset().first()
        if sub is None:
            raise RecordNotFoundError("Cannot cancel: No active subscription found.")

        serializer = CancelSubscriptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        immediately = serializer.validated_data.get("immediately", False)

        canceled_sub = services.cancel_subscription(
            subscription=sub,
            actor=request.user,
            immediately=immediately,
        )

        return Response(self.get_serializer(canceled_sub).data, status=status.HTTP_200_OK)


class UsageCounterViewSet(TenantScopedReadOnlyModelViewSet):
    """Tenant resource usage counters."""

    module_key = "billing"
    required_permission = "billing.view"
    serializer_class = UsageCounterSerializer
    lookup_field = "public_id"
    queryset = UsageCounter.objects.none()

    def get_queryset(self) -> Any:
        if getattr(self, "swagger_fake_view", False):
            return UsageCounter.objects.none()
        org = self.get_tenant()
        return UsageCounter.all_tenants.filter(organization=org).order_by("-period_start", "metric")


class SubscriptionInvoiceViewSet(TenantScopedReadOnlyModelViewSet):
    """Tenant subscription invoice history endpoint."""

    module_key = "billing"
    required_permission = "billing.view"
    serializer_class = SubscriptionInvoiceSerializer
    lookup_field = "public_id"
    queryset = SubscriptionInvoice.objects.none()

    def get_queryset(self) -> Any:
        if getattr(self, "swagger_fake_view", False):
            return SubscriptionInvoice.objects.none()
        org = self.get_tenant()
        return SubscriptionInvoice.all_tenants.filter(organization=org).order_by("-created_at")


@extend_schema(
    summary="Receive payment gateway webhook events",
    description="Public webhook endpoint authenticated via HMAC-SHA256 signature verification.",
    request=None,
    responses={
        200: OpenApiResponse(description="Webhook processed successfully or duplicate ignored."),
        400: OpenApiResponse(description="Invalid signature or malformed payload."),
    },
)
class GatewayWebhookView(APIView):
    """Endpoint receiving external payment gateway webhook notifications.

    Publicly reachable; authenticated via HMAC-SHA256 signature verification.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes: list[Any] = []
    public_endpoint = True

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        signature = (
            request.headers.get("X-Signature")
            or request.headers.get("Stripe-Signature")
            or request.META.get("HTTP_X_SIGNATURE", "")
        )
        raw_payload = request.body
        gateway = get_payment_gateway()

        if not gateway.verify_webhook_signature(payload=raw_payload, signature=signature):
            logger.warning("Gateway webhook rejected: invalid signature.")
            return Response({"error": "Invalid webhook signature."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            event = gateway.parse_webhook_event(payload=raw_payload)
        except Exception as exc:
            logger.error("Failed to parse gateway webhook payload: %s", exc)
            return Response({"error": "Malformed webhook payload."}, status=status.HTTP_400_BAD_REQUEST)

        result = services.process_gateway_webhook_event(event)
        return Response(result, status=status.HTTP_200_OK)
