"""DRF ViewSets for the full accounting module."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounting import services
from apps.accounting.api.serializers import (
    AccountCreateSerializer,
    AccountSerializer,
    BankAccountCreateSerializer,
    BankAccountSerializer,
    BankReconciliationCreateSerializer,
    BankReconciliationSerializer,
    BankTransactionCreateSerializer,
    BankTransactionSerializer,
    ExchangeRateCreateSerializer,
    ExchangeRateSerializer,
    ExpenseCategoryCreateSerializer,
    ExpenseCategorySerializer,
    ExpenseCreateSerializer,
    ExpenseSerializer,
    FiscalPeriodSerializer,
    JournalEntrySerializer,
    ManualJournalCreateSerializer,
    TaxPeriodSummarySerializer,
)
from apps.accounting.models import (
    Account,
    BankAccount,
    ExchangeRate,
    Expense,
    ExpenseCategory,
    FiscalPeriod,
    JournalEntry,
    TaxPeriodSummary,
)
from apps.core.api.idempotency import idempotent
from apps.core.api.viewsets import TenantScopedModelViewSet


@extend_schema_view(
    list=extend_schema(tags=["Accounting"], summary="List chart of accounts"),
    retrieve=extend_schema(tags=["Accounting"], summary="Retrieve account details"),
)
class AccountViewSet(TenantScopedModelViewSet):
    queryset = Account.objects.select_related("parent").all()
    serializer_class = AccountSerializer
    lookup_field = "public_id"
    module_key = "accounting"
    permission_map = {
        "list": "accounting.view",
        "retrieve": "accounting.view",
        "create": "accounting.manage",
        "update": "accounting.manage",
        "partial_update": "accounting.manage",
        "destroy": "accounting.manage",
    }
    search_fields = ["code", "name"]
    ordering_fields = ["code", "name", "type"]
    ordering = ["code"]

    @extend_schema(
        tags=["Accounting"],
        summary="Create a new GL account",
        request=AccountCreateSerializer,
        responses={201: AccountSerializer},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = AccountCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        parent = None
        if data.get("parent_id"):
            parent = Account.all_tenants.get(pk=data["parent_id"], organization=self.get_tenant())

        account = services.create_account(
            organization=self.get_tenant(),
            code=data["code"],
            name=data["name"],
            type=data["type"],
            parent=parent,
            currency=data.get("currency", ""),
            is_control=data.get("is_control", False),
            is_active=data.get("is_active", True),
            description=data.get("description", ""),
            actor=request.user,
        )
        return Response(AccountSerializer(account).data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    list=extend_schema(tags=["Accounting"], summary="List journal entries"),
    retrieve=extend_schema(tags=["Accounting"], summary="Retrieve journal entry details"),
)
class JournalEntryViewSet(TenantScopedModelViewSet):
    queryset = JournalEntry.objects.prefetch_related("lines__account", "reversed_by").all()
    serializer_class = JournalEntrySerializer
    lookup_field = "public_id"
    module_key = "accounting"
    permission_map = {
        "list": "accounting.view",
        "retrieve": "accounting.view",
        "create": "accounting.post",
        "reverse": "accounting.post",
    }
    search_fields = ["entry_number", "memo", "source_type", "source_id"]
    ordering_fields = ["date", "entry_number", "total_debit"]
    ordering = ["-date", "-entry_number"]

    @extend_schema(
        tags=["Accounting"],
        summary="Post a manual journal entry",
        request=ManualJournalCreateSerializer,
        responses={201: JournalEntrySerializer},
    )
    @idempotent
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = ManualJournalCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        org = self.get_tenant()
        line_inputs = []
        for l_data in data["lines"]:
            acct = Account.all_tenants.get(pk=l_data["account_id"], organization=org)
            line_inputs.append(
                services.JournalLineInput(
                    account=acct,
                    debit=Decimal(str(l_data["debit"])),
                    credit=Decimal(str(l_data["credit"])),
                    memo=l_data.get("memo", ""),
                    currency=l_data.get("currency", "USD"),
                    fx_rate=Decimal(str(l_data.get("fx_rate", 1))),
                )
            )

        entry = services.create_manual_journal_entry(
            organization=org,
            date=data["date"],
            memo=data["memo"],
            lines=line_inputs,
            actor=request.user,
        )
        return Response(JournalEntrySerializer(entry).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=["Accounting"],
        summary="Reverse a posted journal entry",
        request=None,
        responses={200: JournalEntrySerializer},
    )
    @action(detail=True, methods=["post"], url_path="reverse")
    @idempotent
    def reverse_entry(self, request: Request, public_id: str | None = None) -> Response:
        entry = self.get_object()
        data = request.data if isinstance(request.data, dict) else {}
        reason = str(data.get("reason", "Manual reversal"))
        services.reverse_entry(
            organization=self.get_tenant(),
            entry=entry,
            date=timezone.now().date(),
            reason=reason,
            actor=request.user,
        )
        entry.refresh_from_db()
        return Response(JournalEntrySerializer(entry).data)


@extend_schema_view(
    list=extend_schema(tags=["Accounting"], summary="List bank accounts"),
    retrieve=extend_schema(tags=["Accounting"], summary="Retrieve bank account details"),
)
class BankAccountViewSet(TenantScopedModelViewSet):
    queryset = BankAccount.objects.select_related("gl_account").all()
    serializer_class = BankAccountSerializer
    lookup_field = "public_id"
    module_key = "accounting"
    permission_map = {
        "list": "accounting.view",
        "retrieve": "accounting.view",
        "create": "accounting.create",
        "record_transaction": "accounting.create",
        "reconcile": "accounting.manage",
    }
    search_fields = ["name", "account_number", "bank_name"]
    ordering = ["name"]

    @extend_schema(
        tags=["Accounting"],
        summary="Create a new bank account",
        request=BankAccountCreateSerializer,
        responses={201: BankAccountSerializer},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = BankAccountCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        org = self.get_tenant()
        gl_acct = Account.all_tenants.get(pk=data["gl_account_id"], organization=org)

        ba = services.create_bank_account(
            organization=org,
            name=data["name"],
            account_number=data["account_number"],
            bank_name=data["bank_name"],
            gl_account=gl_acct,
            currency=data.get("currency", "USD"),
            opening_balance=Decimal(str(data.get("opening_balance", 0))),
            routing_number=data.get("routing_number", ""),
            swift_bic=data.get("swift_bic", ""),
            notes=data.get("notes", ""),
            actor=request.user,
        )
        return Response(BankAccountSerializer(ba).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=["Accounting"],
        summary="Record a transaction on a bank account",
        request=BankTransactionCreateSerializer,
        responses={201: BankTransactionSerializer},
    )
    @action(detail=True, methods=["post"], url_path="transactions")
    @idempotent
    def record_transaction(self, request: Request, public_id: str | None = None) -> Response:
        ba = self.get_object()
        serializer = BankTransactionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        tx = services.record_bank_transaction(
            organization=self.get_tenant(),
            bank_account=ba,
            date=data["date"],
            amount=Decimal(str(data["amount"])),
            transaction_type=data["transaction_type"],
            reference=data.get("reference", ""),
            payee=data.get("payee", ""),
            description=data.get("description", ""),
            actor=request.user,
        )
        return Response(BankTransactionSerializer(tx).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=["Accounting"],
        summary="Reconcile bank account transactions",
        request=BankReconciliationCreateSerializer,
        responses={201: BankReconciliationSerializer},
    )
    @action(detail=True, methods=["post"], url_path="reconcile")
    @idempotent
    def reconcile(self, request: Request, public_id: str | None = None) -> Response:
        ba = self.get_object()
        serializer = BankReconciliationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        rec = services.reconcile_bank_statement(
            organization=self.get_tenant(),
            bank_account=ba,
            statement_date=data["statement_date"],
            statement_ending_balance=Decimal(str(data["statement_ending_balance"])),
            cleared_transaction_ids=data["cleared_transaction_ids"],
            actor=request.user,
        )
        return Response(BankReconciliationSerializer(rec).data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    list=extend_schema(tags=["Accounting"], summary="List expense categories"),
    retrieve=extend_schema(tags=["Accounting"], summary="Retrieve expense category details"),
)
class ExpenseCategoryViewSet(TenantScopedModelViewSet):
    queryset = ExpenseCategory.objects.select_related("gl_account").all()
    serializer_class = ExpenseCategorySerializer
    lookup_field = "public_id"
    module_key = "accounting"
    permission_map = {
        "list": "accounting.view",
        "retrieve": "accounting.view",
        "create": "accounting.create",
        "update": "accounting.update",
        "destroy": "accounting.delete",
    }
    search_fields = ["name", "code"]
    ordering = ["name"]

    @extend_schema(
        tags=["Accounting"],
        summary="Create an expense category",
        request=ExpenseCategoryCreateSerializer,
        responses={201: ExpenseCategorySerializer},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = ExpenseCategoryCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        gl_acct = Account.all_tenants.get(pk=data["gl_account_id"], organization=self.get_tenant())
        cat = services.create_expense_category(
            organization=self.get_tenant(),
            name=data["name"],
            code=data["code"],
            gl_account=gl_acct,
            description=data.get("description", ""),
            actor=request.user,
        )
        return Response(ExpenseCategorySerializer(cat).data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    list=extend_schema(tags=["Accounting"], summary="List expenses"),
    retrieve=extend_schema(tags=["Accounting"], summary="Retrieve expense details"),
)
class ExpenseViewSet(TenantScopedModelViewSet):
    queryset = Expense.objects.select_related(
        "category", "paid_from_account", "bank_account", "journal_entry"
    ).all()
    serializer_class = ExpenseSerializer
    lookup_field = "public_id"
    module_key = "accounting"
    permission_map = {
        "list": "accounting.view",
        "retrieve": "accounting.view",
        "create": "accounting.create",
        "post_expense": "accounting.post",
        "void_expense": "accounting.post",
    }
    search_fields = ["expense_number", "vendor_name", "reference", "notes"]
    ordering = ["-date", "-created_at"]

    @extend_schema(
        tags=["Accounting"],
        summary="Create a draft expense",
        request=ExpenseCreateSerializer,
        responses={201: ExpenseSerializer},
    )
    @idempotent
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = ExpenseCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        org = self.get_tenant()
        cat = ExpenseCategory.all_tenants.get(pk=data["category_id"], organization=org)
        paid_from = Account.all_tenants.get(pk=data["paid_from_account_id"], organization=org)
        ba = None
        if data.get("bank_account_id"):
            ba = BankAccount.all_tenants.get(pk=data["bank_account_id"], organization=org)

        exp = services.create_expense(
            organization=org,
            category=cat,
            paid_from_account=paid_from,
            bank_account=ba,
            date=data["date"],
            amount=Decimal(str(data["amount"])),
            tax_rate=Decimal(str(data.get("tax_rate", 0))),
            currency=data.get("currency", "USD"),
            exchange_rate=Decimal(str(data.get("exchange_rate", 1))),
            payment_method=data.get("payment_method", "cash"),
            vendor_name=data.get("vendor_name", ""),
            reference=data.get("reference", ""),
            notes=data.get("notes", ""),
            actor=request.user,
        )
        return Response(ExpenseSerializer(exp).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=["Accounting"],
        summary="Post an expense to general ledger",
        request=None,
        responses={200: ExpenseSerializer},
    )
    @action(detail=True, methods=["post"], url_path="post")
    @idempotent
    def post_expense(self, request: Request, public_id: str | None = None) -> Response:
        exp = self.get_object()
        posted = services.post_expense(organization=self.get_tenant(), expense=exp, actor=request.user)
        return Response(ExpenseSerializer(posted).data)

    @extend_schema(
        tags=["Accounting"],
        summary="Void a posted expense and reverse journal entry",
        request=None,
        responses={200: ExpenseSerializer},
    )
    @action(detail=True, methods=["post"], url_path="void")
    @idempotent
    def void_expense(self, request: Request, public_id: str | None = None) -> Response:
        exp = self.get_object()
        voided = services.void_expense(organization=self.get_tenant(), expense=exp, actor=request.user)
        return Response(ExpenseSerializer(voided).data)


@extend_schema_view(
    list=extend_schema(tags=["Accounting"], summary="List exchange rates"),
    retrieve=extend_schema(tags=["Accounting"], summary="Retrieve exchange rate"),
)
class ExchangeRateViewSet(TenantScopedModelViewSet):
    queryset = ExchangeRate.objects.all()
    serializer_class = ExchangeRateSerializer
    lookup_field = "public_id"
    module_key = "accounting"
    permission_map = {
        "list": "accounting.view",
        "retrieve": "accounting.view",
        "create": "accounting.update",
    }
    ordering = ["-effective_date"]

    @extend_schema(
        tags=["Accounting"],
        summary="Record a currency exchange rate",
        request=ExchangeRateCreateSerializer,
        responses={201: ExchangeRateSerializer},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = ExchangeRateCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        rate_obj = services.record_exchange_rate(
            organization=self.get_tenant(),
            from_currency=data["from_currency"],
            to_currency=data["to_currency"],
            rate=Decimal(str(data["rate"])),
            effective_date=data["effective_date"],
            source=data.get("source", "manual"),
            actor=request.user,
        )
        return Response(ExchangeRateSerializer(rate_obj).data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    list=extend_schema(tags=["Accounting"], summary="List fiscal periods"),
    retrieve=extend_schema(tags=["Accounting"], summary="Retrieve fiscal period details"),
)
class FiscalPeriodViewSet(TenantScopedModelViewSet):
    queryset = FiscalPeriod.objects.select_related("fiscal_year").all()
    serializer_class = FiscalPeriodSerializer
    lookup_field = "public_id"
    module_key = "accounting"
    permission_map = {
        "list": "accounting.view",
        "retrieve": "accounting.view",
        "close": "accounting.close_period",
        "reopen": "accounting.close_period",
    }
    ordering = ["-start_date"]

    @extend_schema(
        tags=["Accounting"],
        summary="Close a fiscal period",
        request=None,
        responses={200: FiscalPeriodSerializer},
    )
    @action(detail=True, methods=["post"], url_path="close")
    def close_period(self, request: Request, public_id: str | None = None) -> Response:
        period = self.get_object()
        closed = services.close_fiscal_period(
            organization=self.get_tenant(), period=period, actor=request.user
        )
        return Response(FiscalPeriodSerializer(closed).data)

    @extend_schema(
        tags=["Accounting"],
        summary="Reopen a fiscal period",
        request=None,
        responses={200: FiscalPeriodSerializer},
    )
    @action(detail=True, methods=["post"], url_path="reopen")
    def reopen_period(self, request: Request, public_id: str | None = None) -> Response:
        period = self.get_object()
        reopened = services.reopen_fiscal_period(
            organization=self.get_tenant(), period=period, actor=request.user
        )
        return Response(FiscalPeriodSerializer(reopened).data)


@extend_schema_view(
    list=extend_schema(tags=["Accounting"], summary="List tax period summaries"),
    retrieve=extend_schema(tags=["Accounting"], summary="Retrieve tax period summary"),
)
class TaxPeriodSummaryViewSet(TenantScopedModelViewSet):
    queryset = TaxPeriodSummary.objects.all()
    serializer_class = TaxPeriodSummarySerializer
    lookup_field = "public_id"
    module_key = "accounting"
    permission_map = {
        "list": "accounting.view",
        "retrieve": "accounting.view",
        "create": "accounting.manage",
        "file": "accounting.manage",
    }
    ordering = ["-period_end"]

    @extend_schema(
        tags=["Accounting"],
        summary="Calculate and save tax period summary",
        request=None,
        responses={201: TaxPeriodSummarySerializer},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        data = request.data if isinstance(request.data, dict) else {}
        start_str = data.get("period_start")
        end_str = data.get("period_end")
        if not start_str or not end_str:
            raise ValidationError("period_start and period_end are required.")

        start = datetime.date.fromisoformat(str(start_str))
        end = datetime.date.fromisoformat(str(end_str))
        summary = services.calculate_tax_period_summary(
            organization=self.get_tenant(),
            period_start=start,
            period_end=end,
            save=True,
            notes=str(data.get("notes", "")),
            actor=request.user,
        )
        return Response(TaxPeriodSummarySerializer(summary).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="calculate")
    def calculate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self.create(request, *args, **kwargs)

    def _do_file(self, request: Request) -> Response:
        summary = self.get_object()
        filed = services.file_tax_period_summary(
            organization=self.get_tenant(), summary=summary, actor=request.user
        )
        return Response(TaxPeriodSummarySerializer(filed).data)

    @extend_schema(
        tags=["Accounting"],
        summary="Mark tax period summary as filed",
        request=None,
        responses={200: TaxPeriodSummarySerializer},
    )
    @action(detail=True, methods=["post"], url_path="file")
    def file_summary(self, request: Request, public_id: str | None = None) -> Response:
        return self._do_file(request)

    @action(detail=True, methods=["post"], url_path="file_return")
    def file_return(self, request: Request, public_id: str | None = None) -> Response:
        return self._do_file(request)
