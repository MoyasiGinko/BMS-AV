"""URL patterns for the Accounting web UI."""

from __future__ import annotations

from django.urls import path

from apps.accounting import views

app_name = "accounting"

urlpatterns = [
    path("", views.accounting_dashboard, name="dashboard"),
    # Chart of Accounts
    path("accounts/", views.account_list, name="account_list"),
    path("accounts/new/", views.account_create, name="account_create"),
    # Manual Journals
    path("journals/", views.journal_list, name="journal_list"),
    path("journals/new/", views.journal_create, name="journal_create"),
    path("journals/<int:pk>/", views.journal_detail, name="journal_detail"),
    path("journals/<int:pk>/reverse/", views.journal_reverse, name="journal_reverse"),
    # Bank Accounts & Reconciliation
    path("banking/", views.bank_account_list, name="bank_account_list"),
    path("banking/new/", views.bank_account_create, name="bank_account_create"),
    path("banking/<int:pk>/", views.bank_account_detail, name="bank_account_detail"),
    path("banking/<int:pk>/transactions/new/", views.bank_transaction_create, name="bank_transaction_create"),
    path("banking/<int:pk>/reconcile/", views.bank_reconcile, name="bank_reconcile"),
    # Expenses & Categories
    path("expenses/", views.expense_list, name="expense_list"),
    path("expenses/new/", views.expense_create, name="expense_create"),
    path("expenses/<int:pk>/", views.expense_detail, name="expense_detail"),
    path("expenses/<int:pk>/post/", views.expense_post, name="expense_post"),
    path("expenses/<int:pk>/void/", views.expense_void, name="expense_void"),
    path("expenses/categories/", views.expense_category_list, name="expense_category_list"),
    # Currencies & FX
    path("currencies/", views.currency_list, name="currency_list"),
    # Fiscal Periods & Closing
    path("periods/", views.fiscal_period_list, name="fiscal_period_list"),
    path("periods/<int:pk>/close/", views.fiscal_period_close, name="fiscal_period_close"),
    path("periods/<int:pk>/reopen/", views.fiscal_period_reopen, name="fiscal_period_reopen"),
    # Tax Summary
    path("tax-summary/", views.tax_summary, name="tax_summary"),
]
