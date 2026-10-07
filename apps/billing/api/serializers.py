"""DRF serializers for billing models."""

from __future__ import annotations

from rest_framework import serializers

from apps.billing.models import Module, Plan, PlanModule, Subscription, UsageCounter


class ModuleSerializer(serializers.ModelSerializer[Module]):
    """Serializer for platform functional module definitions."""

    class Meta:
        model = Module
        fields = ["key", "name", "description", "icon", "is_beta", "sort_order"]


class PlanModuleSerializer(serializers.ModelSerializer[PlanModule]):
    """Serializer representing module inclusion within a plan tier."""

    module_key = serializers.CharField(source="module.key", read_only=True)
    module_name = serializers.CharField(source="module.name", read_only=True)

    class Meta:
        model = PlanModule
        fields = ["module_key", "module_name", "included"]


class PlanSerializer(serializers.ModelSerializer[Plan]):
    """Serializer for public and internal subscription plan tiers."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    modules = PlanModuleSerializer(source="plan_modules", many=True, read_only=True)

    class Meta:
        model = Plan
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "price_monthly",
            "price_yearly",
            "currency",
            "is_active",
            "trial_days",
            "max_users",
            "max_branches",
            "max_warehouses",
            "modules",
        ]
        read_only_fields = fields


class SubscriptionSerializer(serializers.ModelSerializer[Subscription]):
    """Serializer for tenant subscription state and lifecycle."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    plan = PlanSerializer(read_only=True)
    is_active = serializers.BooleanField(source="is_active_or_trialing", read_only=True)

    class Meta:
        model = Subscription
        fields = [
            "id",
            "plan",
            "status",
            "billing_interval",
            "trial_start",
            "trial_end",
            "current_period_start",
            "current_period_end",
            "renews_at",
            "cancel_at_period_end",
            "canceled_at",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ChangePlanSerializer(serializers.Serializer[dict[str, str]]):
    """Input payload for upgrading or downgrading subscription tier."""

    new_plan_slug = serializers.SlugField(required=True)


class CancelSubscriptionSerializer(serializers.Serializer[dict[str, bool]]):
    """Input payload for canceling subscription."""

    immediately = serializers.BooleanField(default=False)


class UsageCounterSerializer(serializers.ModelSerializer[UsageCounter]):
    """Serializer for tenant resource usage metrics."""

    id = serializers.UUIDField(source="public_id", read_only=True)

    class Meta:
        model = UsageCounter
        fields = [
            "id",
            "metric",
            "value",
            "period_start",
            "period_end",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
