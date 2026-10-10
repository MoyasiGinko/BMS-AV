"""DRF API URL routing for Accounting."""

from __future__ import annotations

from rest_framework.routers import SimpleRouter

from apps.accounting.api.views import (
    AccountViewSet,
    BankAccountViewSet,
    ExchangeRateViewSet,
    ExpenseCategoryViewSet,
    ExpenseViewSet,
    FiscalPeriodViewSet,
    JournalEntryViewSet,
    TaxPeriodSummaryViewSet,
)

app_name = "accounting_api"

router = SimpleRouter()
router.register("accounts", AccountViewSet, basename="account")
router.register("journals", JournalEntryViewSet, basename="journal")
router.register("journal-entries", JournalEntryViewSet, basename="journal-entry")
router.register("bank-accounts", BankAccountViewSet, basename="bank-account")
router.register("expense-categories", ExpenseCategoryViewSet, basename="expense-category")
router.register("expenses", ExpenseViewSet, basename="expense")
router.register("exchange-rates", ExchangeRateViewSet, basename="exchange-rate")
router.register("fiscal-periods", FiscalPeriodViewSet, basename="fiscal-period")
router.register("tax-summaries", TaxPeriodSummaryViewSet, basename="tax-summary")

urlpatterns = router.urls
