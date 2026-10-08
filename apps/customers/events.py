"""Domain events emitted by the customers module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from apps.core.events import DomainEvent


@dataclass(frozen=True)
class CustomerCreated(DomainEvent):
    """Fired when a new customer is created."""

    event_type: ClassVar[str] = "customers.customer_created"

    customer_id: int = 0
    code: str = ""
    name: str = ""


@dataclass(frozen=True)
class CustomerUpdated(DomainEvent):
    """Fired when customer details are updated."""

    event_type: ClassVar[str] = "customers.customer_updated"

    customer_id: int = 0
    code: str = ""
    name: str = ""


@dataclass(frozen=True)
class CustomerBalanceChanged(DomainEvent):
    """Fired when an entry is posted to the customer balance subledger."""

    event_type: ClassVar[str] = "customers.balance_changed"

    customer_id: int = 0
    entry_id: int = 0
    entry_type: str = ""
    debit: str = "0.0000"
    credit: str = "0.0000"
    new_balance: str = "0.0000"
    reference_type: str = ""
    reference_id: str = ""


@dataclass(frozen=True)
class CustomerCreditLimitExceeded(DomainEvent):
    """Fired when a transaction attempts to exceed customer credit limit."""

    event_type: ClassVar[str] = "customers.credit_limit_exceeded"

    customer_id: int = 0
    proposed_amount: str = "0.0000"
    current_balance: str = "0.0000"
    credit_limit: str = "0.0000"
