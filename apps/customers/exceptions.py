"""Exceptions for the customers domain."""

from __future__ import annotations


class CustomerError(Exception):
    """Base domain exception for customer operations."""


class CustomerNotFoundError(CustomerError):
    """Customer not found or not accessible within tenant."""


class CreditLimitExceededError(CustomerError):
    """Transaction exceeds approved credit limit."""


class CustomerSuspendedError(CustomerError):
    """Customer account is suspended and cannot accept new charges."""


class InvalidBalanceMutationError(CustomerError):
    """Invalid debit or credit amount in ledger entry."""


class CustomerHasTransactionsError(CustomerError):
    """Customer with posted balance entries cannot be deleted."""


CreditLimitExceeded = CreditLimitExceededError
CustomerSuspended = CustomerSuspendedError
InvalidBalanceMutation = InvalidBalanceMutationError
CustomerHasTransactions = CustomerHasTransactionsError
