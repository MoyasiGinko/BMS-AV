"""Django admin configuration for customers, addresses, contacts, and balance entries."""

from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from apps.customers.models import (
    Customer,
    CustomerAddress,
    CustomerBalanceEntry,
    CustomerContact,
)


class CustomerAddressInline(admin.TabularInline):
    model = CustomerAddress
    extra = 0


class CustomerContactInline(admin.TabularInline):
    model = CustomerContact
    extra = 0


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "type",
        "status",
        "current_balance",
        "credit_limit",
        "currency",
        "organization",
        "created_at",
    )
    list_filter = ("status", "type", "currency")
    search_fields = ("name", "code", "email", "phone", "tax_id")
    inlines = [CustomerAddressInline, CustomerContactInline]


@admin.register(CustomerAddress)
class CustomerAddressAdmin(admin.ModelAdmin):
    list_display = ("customer", "type", "line1", "city", "country", "is_default", "organization")
    list_filter = ("type", "is_default", "country")
    search_fields = ("customer__name", "customer__code", "line1", "city", "recipient_name")


@admin.register(CustomerContact)
class CustomerContactAdmin(admin.ModelAdmin):
    list_display = (
        "first_name",
        "last_name",
        "customer",
        "title",
        "email",
        "phone",
        "is_primary",
        "organization",
    )
    list_filter = ("is_primary",)
    search_fields = ("first_name", "last_name", "customer__name", "customer__code", "email")


@admin.register(CustomerBalanceEntry)
class CustomerBalanceEntryAdmin(admin.ModelAdmin):
    list_display = (
        "occurred_at",
        "customer",
        "entry_type",
        "debit",
        "credit",
        "balance_after",
        "reference_number",
        "organization",
    )
    list_filter = ("entry_type",)
    search_fields = ("customer__name", "customer__code", "reference_number", "description")
    readonly_fields = [f.name for f in CustomerBalanceEntry._meta.fields]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False
