"""Exceptions for accounting and ledger operations."""

from __future__ import annotations


class AccountingError(Exception):
    """Base exception for all accounting domain errors."""


class PeriodClosed(AccountingError):
    """Raised when an operation attempts to post into a closed fiscal period."""


class UnbalancedEntryError(AccountingError):
    """Raised when sum(debits) != sum(credits) in a journal entry."""


class AccountNotFoundError(AccountingError):
    """Raised when an account code or account mapping cannot be resolved."""


class AccountInactiveError(AccountingError):
    """Raised when attempting to post to an inactive account."""


class InvalidEntryStateError(AccountingError):
    """Raised when an entry is not in the required state for an operation."""


class AlreadyReversedError(AccountingError):
    """Raised when attempting to reverse an entry that has already been reversed."""


class EmptyEntryError(AccountingError):
    """Raised when an entry has zero amount or zero total debits/credits."""


class InvalidEntryError(AccountingError):
    """Raised when an entry does not meet basic structural requirements."""


class ExpenseAlreadyPostedError(AccountingError):
    """Raised when attempting to post an expense that is not in draft status."""


class ExpenseAlreadyVoidError(AccountingError):
    """Raised when attempting to void an already voided or invalid expense."""


class BankReconciliationError(AccountingError):
    """Raised when reconciliation parameters or transactions are invalid."""
