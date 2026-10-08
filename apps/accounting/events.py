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
