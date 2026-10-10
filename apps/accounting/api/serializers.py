"""DRF serializers for the full accounting module."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from rest_framework import serializers

from apps.accounting.models import (
    Account,
    AccountType,
    BankAccount,
    BankReconciliation,
    BankTransaction,
    BankTransactionType,
    ExchangeRate,
    Expense,
    ExpenseCategory,
    ExpensePaymentMethod,
    FiscalPeriod,
    JournalEntry,
    JournalLine,
    TaxPeriodSummary,
)


class AccountSerializer(serializers.ModelSerializer):
    parent_code = serializers.CharField(source="parent.code", read_only=True, default=None)

    class Meta:
        model = Account
        fields = [
            "id",
            "public_id",
            "code",
            "name",
            "type",
            "parent",
            "parent_code",
            "currency",
            "is_control",
            "is_active",
            "description",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "public_id", "created_at", "updated_at"]


class AccountCreateSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=32)
    name = serializers.CharField(max_length=128)
    type = serializers.ChoiceField(choices=AccountType.choices)
    parent_id = serializers.IntegerField(required=False, allow_null=True)
    currency = serializers.CharField(max_length=3, required=False, default="")
    is_control = serializers.BooleanField(required=False, default=False)
    is_active = serializers.BooleanField(required=False, default=True)
    description = serializers.CharField(max_length=255, required=False, default="", allow_blank=True)


class JournalLineSerializer(serializers.ModelSerializer):
    account_code = serializers.CharField(source="account.code", read_only=True)
    account_name = serializers.CharField(source="account.name", read_only=True)

    class Meta:
        model = JournalLine
        fields = [
            "id",
            "line_number",
            "account",
            "account_code",
            "account_name",
            "debit",
            "credit",
            "currency",
            "fx_rate",
            "base_amount",
            "memo",
        ]
        read_only_fields = ["id", "line_number", "base_amount"]


class JournalEntrySerializer(serializers.ModelSerializer):
    lines = JournalLineSerializer(many=True, read_only=True)

    class Meta:
        model = JournalEntry
        fields = [
            "id",
            "public_id",
            "entry_number",
            "date",
            "memo",
            "status",
            "source_type",
            "source_id",
            "total_debit",
            "total_credit",
            "lines",
            "created_at",
            "posted_at",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "entry_number",
            "status",
            "total_debit",
            "total_credit",
            "created_at",
            "posted_at",
        ]


class JournalLineInputSerializer(serializers.Serializer):
    account_id = serializers.IntegerField()
    debit = serializers.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0.0000"))
    credit = serializers.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0.0000"))
    memo = serializers.CharField(max_length=255, required=False, default="", allow_blank=True)
    currency = serializers.CharField(max_length=3, required=False, default="USD")
    fx_rate = serializers.DecimalField(max_digits=18, decimal_places=6, default=Decimal("1.000000"))


class ManualJournalCreateSerializer(serializers.Serializer):
    date = serializers.DateField()
    memo = serializers.CharField()
    lines = JournalLineInputSerializer(many=True)

    def validate_lines(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(value) < 2:
            raise serializers.ValidationError("Journal entry must contain at least 2 lines.")
        total_dr = sum((Decimal(str(line_item.get("debit", 0))) for line_item in value), Decimal("0.0000"))
        total_cr = sum((Decimal(str(line_item.get("credit", 0))) for line_item in value), Decimal("0.0000"))
        if total_dr != total_cr:
            raise serializers.ValidationError(
                f"Journal is unbalanced: total debits ({total_dr}) != total credits ({total_cr})."
            )
        return value


class BankAccountSerializer(serializers.ModelSerializer):
    gl_account_code = serializers.CharField(source="gl_account.code", read_only=True)

    class Meta:
        model = BankAccount
        fields = [
            "id",
            "public_id",
            "name",
            "account_number",
            "bank_name",
            "routing_number",
            "swift_bic",
            "currency",
            "current_balance",
            "gl_account",
            "gl_account_code",
            "is_active",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "public_id", "current_balance", "created_at", "updated_at"]


class BankAccountCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=128)
    account_number = serializers.CharField(max_length=64)
    bank_name = serializers.CharField(max_length=128)
    gl_account_id = serializers.IntegerField()
    routing_number = serializers.CharField(max_length=64, required=False, default="", allow_blank=True)
    swift_bic = serializers.CharField(max_length=32, required=False, default="", allow_blank=True)
    currency = serializers.CharField(max_length=3, required=False, default="USD")
    opening_balance = serializers.DecimalField(
        max_digits=18, decimal_places=4, required=False, default=Decimal("0.0000")
    )
    notes = serializers.CharField(required=False, default="", allow_blank=True)


class BankTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankTransaction
        fields = [
            "id",
            "public_id",
            "bank_account",
            "date",
            "amount",
            "transaction_type",
            "reference",
            "payee",
            "description",
            "is_reconciled",
            "reconciled_at",
            "created_at",
        ]
        read_only_fields = ["id", "public_id", "is_reconciled", "reconciled_at", "created_at"]


class BankTransactionCreateSerializer(serializers.Serializer):
    date = serializers.DateField()
    amount = serializers.DecimalField(max_digits=18, decimal_places=4)
    transaction_type = serializers.ChoiceField(choices=BankTransactionType.choices)
    reference = serializers.CharField(max_length=64, required=False, default="", allow_blank=True)
    payee = serializers.CharField(max_length=128, required=False, default="", allow_blank=True)
    description = serializers.CharField(max_length=255, required=False, default="", allow_blank=True)


class BankReconciliationSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankReconciliation
        fields = [
            "id",
            "public_id",
            "bank_account",
            "statement_date",
            "statement_ending_balance",
            "book_balance",
            "reconciled_balance",
            "difference",
            "status",
            "reconciled_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "book_balance",
            "reconciled_balance",
            "difference",
            "status",
            "reconciled_at",
            "created_at",
        ]


class BankReconciliationCreateSerializer(serializers.Serializer):
    statement_date = serializers.DateField()
    statement_ending_balance = serializers.DecimalField(max_digits=18, decimal_places=4)
    cleared_transaction_ids = serializers.ListField(child=serializers.IntegerField())


class ExpenseCategorySerializer(serializers.ModelSerializer):
    gl_account_code = serializers.CharField(source="gl_account.code", read_only=True)

    class Meta:
        model = ExpenseCategory
        fields = [
            "id",
            "public_id",
            "name",
            "code",
            "gl_account",
            "gl_account_code",
            "description",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "public_id", "created_at"]


class ExpenseCategoryCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=128)
    code = serializers.CharField(max_length=32)
    gl_account_id = serializers.IntegerField()
    description = serializers.CharField(max_length=255, required=False, default="", allow_blank=True)


class ExpenseSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    category_code = serializers.CharField(source="category.code", read_only=True)
    paid_from_code = serializers.CharField(source="paid_from_account.code", read_only=True)

    class Meta:
        model = Expense
        fields = [
            "id",
            "public_id",
            "expense_number",
            "category",
            "category_name",
            "category_code",
            "paid_from_account",
            "paid_from_code",
            "bank_account",
            "date",
            "amount",
            "tax_amount",
            "total_amount",
            "tax_rate",
            "currency",
            "exchange_rate",
            "base_amount",
            "payment_method",
            "vendor_name",
            "reference",
            "notes",
            "status",
            "journal_entry",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "expense_number",
            "tax_amount",
            "total_amount",
            "base_amount",
            "status",
            "journal_entry",
            "created_at",
        ]


class ExpenseCreateSerializer(serializers.Serializer):
    category_id = serializers.IntegerField()
    paid_from_account_id = serializers.IntegerField()
    bank_account_id = serializers.IntegerField(required=False, allow_null=True)
    date = serializers.DateField()
    amount = serializers.DecimalField(max_digits=18, decimal_places=4)
    tax_rate = serializers.DecimalField(
        max_digits=6, decimal_places=4, required=False, default=Decimal("0.0000")
    )
    currency = serializers.CharField(max_length=3, required=False, default="USD")
    exchange_rate = serializers.DecimalField(
        max_digits=18, decimal_places=6, required=False, default=Decimal("1.000000")
    )
    payment_method = serializers.ChoiceField(
        choices=ExpensePaymentMethod.choices, required=False, default=ExpensePaymentMethod.CASH
    )
    vendor_name = serializers.CharField(max_length=128, required=False, default="", allow_blank=True)
    reference = serializers.CharField(max_length=64, required=False, default="", allow_blank=True)
    notes = serializers.CharField(required=False, default="", allow_blank=True)


class ExchangeRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExchangeRate
        fields = [
            "id",
            "public_id",
            "from_currency",
            "to_currency",
            "rate",
            "effective_date",
            "source",
            "created_at",
        ]
        read_only_fields = ["id", "public_id", "created_at"]


class ExchangeRateCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExchangeRate
        fields = [
            "from_currency",
            "to_currency",
            "rate",
            "effective_date",
            "source",
        ]


class FiscalPeriodSerializer(serializers.ModelSerializer):
    class Meta:
        model = FiscalPeriod
        fields = [
            "id",
            "public_id",
            "fiscal_year",
            "period_number",
            "name",
            "start_date",
            "end_date",
            "status",
            "closed_at",
        ]
        read_only_fields = ["id", "public_id", "status", "closed_at"]


class TaxPeriodSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxPeriodSummary
        fields = [
            "id",
            "public_id",
            "period_start",
            "period_end",
            "taxable_sales",
            "output_tax",
            "taxable_purchases",
            "input_tax",
            "net_tax_payable",
            "status",
            "notes",
            "filed_at",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "taxable_sales",
            "output_tax",
            "taxable_purchases",
            "input_tax",
            "net_tax_payable",
            "status",
            "filed_at",
        ]
