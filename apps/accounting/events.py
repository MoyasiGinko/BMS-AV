"""Domain events emitted by the accounting module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from apps.core.events import DomainEvent


@dataclass(frozen=True)
class JournalEntryPosted(DomainEvent):
    """Fired when a balanced journal entry is posted to the ledger."""

    event_type: ClassVar[str] = "accounting.entry_posted"

    entry_id: int = 0
    entry_number: str = ""
    entry_date: str = ""
    total_amount: str = ""
    source_type: str = ""
    source_id: str = ""


@dataclass(frozen=True)
class JournalEntryReversed(DomainEvent):
    """Fired when an existing posted journal entry is reversed."""

    event_type: ClassVar[str] = "accounting.entry_reversed"

    entry_id: int = 0
    reversal_entry_id: int = 0
    entry_number: str = ""
    reversal_number: str = ""
    reason: str = ""


@dataclass(frozen=True)
class FiscalPeriodClosed(DomainEvent):
    """Fired when a fiscal period is officially closed against further postings."""

    event_type: ClassVar[str] = "accounting.period_closed"

    period_id: int = 0
    period_name: str = ""
    fiscal_year_id: int | None = None


@dataclass(frozen=True)
class ExpenseCreated(DomainEvent):
    """Fired when an expense is recorded in draft status."""

    event_type: ClassVar[str] = "accounting.expense_created"

    expense_id: int = 0
    expense_number: str = ""
    total_amount: str = ""
    vendor_name: str = ""


@dataclass(frozen=True)
class ExpensePosted(DomainEvent):
    """Fired when an expense is posted to the ledger."""

    event_type: ClassVar[str] = "accounting.expense_posted"

    expense_id: int = 0
    expense_number: str = ""
    journal_entry_id: int = 0
    total_amount: str = ""


@dataclass(frozen=True)
class ExpenseVoided(DomainEvent):
    """Fired when a posted expense is voided and its journal reversed."""

    event_type: ClassVar[str] = "accounting.expense_voided"

    expense_id: int = 0
    expense_number: str = ""


@dataclass(frozen=True)
class BankAccountCreated(DomainEvent):
    """Fired when a new bank account is registered."""

    event_type: ClassVar[str] = "accounting.bank_account_created"

    bank_account_id: int = 0
    name: str = ""
    account_number: str = ""


@dataclass(frozen=True)
class BankReconciliationCompleted(DomainEvent):
    """Fired when a bank statement reconciliation is completed."""

    event_type: ClassVar[str] = "accounting.bank_reconciliation_completed"

    reconciliation_id: int = 0
    bank_account_id: int = 0
    statement_date: str = ""
    statement_ending_balance: str = ""


@dataclass(frozen=True)
class ExchangeRateUpdated(DomainEvent):
    """Fired when a currency exchange rate is recorded."""

    event_type: ClassVar[str] = "accounting.exchange_rate_updated"

    rate_id: int = 0
    from_currency: str = ""
    to_currency: str = ""
    rate: str = ""
    effective_date: str = ""
