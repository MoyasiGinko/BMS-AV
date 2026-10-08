"""Django admin registration for accounting models."""

from __future__ import annotations

from django.contrib import admin

from apps.accounting.models import (
    Account,
    AccountMapping,
    FiscalPeriod,
    FiscalYear,
    JournalEntry,
    JournalLine,
)


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "type", "currency", "is_control", "is_active", "organization")
    list_filter = ("type", "is_control", "is_active")
    search_fields = ("code", "name")
    readonly_fields = ("public_id", "created_at", "updated_at")


@admin.register(AccountMapping)
class AccountMappingAdmin(admin.ModelAdmin):
    list_display = ("mapping_key", "account", "organization")
    search_fields = ("mapping_key", "account__code", "account__name")
    readonly_fields = ("public_id", "created_at", "updated_at")


@admin.register(FiscalYear)
class FiscalYearAdmin(admin.ModelAdmin):
    list_display = ("name", "start_date", "end_date", "is_closed", "organization")
    list_filter = ("is_closed",)
    search_fields = ("name",)
    readonly_fields = ("public_id", "created_at", "updated_at")


@admin.register(FiscalPeriod)
class FiscalPeriodAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "fiscal_year",
        "period_number",
        "start_date",
        "end_date",
        "status",
        "organization",
    )
    list_filter = ("status",)
    search_fields = ("name",)
    readonly_fields = ("public_id", "created_at", "updated_at")


class JournalLineInline(admin.TabularInline):
    model = JournalLine
    extra = 0
    readonly_fields = (
        "line_number",
        "account",
        "debit",
        "credit",
        "currency",
        "fx_rate",
        "base_amount",
        "memo",
        "party_type",
        "party_id",
    )
    can_delete = False


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = (
        "entry_number",
        "date",
        "status",
        "total_debit",
        "total_credit",
        "source_type",
        "source_id",
        "organization",
    )
    list_filter = ("status", "date")
    search_fields = ("entry_number", "memo", "source_type", "source_id")
    readonly_fields = (
        "public_id",
        "entry_number",
        "total_debit",
        "total_credit",
        "posted_at",
        "posted_by",
        "reversed_by",
        "created_at",
        "updated_at",
    )
    inlines = [JournalLineInline]
