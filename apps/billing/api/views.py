"""Billing API viewsets."""

from __future__ import annotations

from typing import Any

from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.billing import services
from apps.billing.api.serializers import (
    CancelSubscriptionSerializer,
    ChangePlanSerializer,
    PlanSerializer,
    SubscriptionSerializer,
    UsageCounterSerializer,
)
from apps.billing.models import Plan, Subscription, UsageCounter
from apps.core.api.idempotency import idempotent
from apps.core.api.viewsets import TenantScopedReadOnlyModelViewSet, TenantScopedViewSet
from apps.core.exceptions import RecordNotFoundError, ValidationError


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
