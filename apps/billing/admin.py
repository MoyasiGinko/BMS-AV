"""Django admin registration for billing models."""

from __future__ import annotations

from django.contrib import admin

from apps.billing.models import Module, Plan, PlanModule, Subscription, UsageCounter


class PlanModuleInline(admin.TabularInline):
    model = PlanModule
    extra = 0
    autocomplete_fields = ["module"]


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "slug",
        "price_monthly",
        "price_yearly",
        "currency",
        "is_active",
        "max_users",
        "max_branches",
        "max_warehouses",
        "sort_order",
    )
    list_filter = ("is_active", "currency")
    search_fields = ("name", "slug")
    inlines = [PlanModuleInline]


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "icon", "is_beta", "sort_order")
    list_filter = ("is_beta",)
    search_fields = ("name", "key")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "organization",
        "plan",
        "status",
        "billing_interval",
        "trial_start",
        "trial_end",
        "current_period_end",
        "cancel_at_period_end",
    )
    list_filter = ("status", "billing_interval", "cancel_at_period_end")
    search_fields = ("organization__name", "plan__name")
    raw_id_fields = ("organization", "plan")


@admin.register(UsageCounter)
class UsageCounterAdmin(admin.ModelAdmin):
    list_display = ("organization", "metric", "value", "period_start", "period_end")
    list_filter = ("metric", "period_start")
    raw_id_fields = ("organization",)
