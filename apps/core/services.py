"""Core services for number sequences and shared cross-domain logic."""

from __future__ import annotations

import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.core.models import NumberSequence


@transaction.atomic
def generate_next_number(
    *,
    organization_id: int,
    name: str,
    prefix: str = "",
    suffix: str = "",
    padding: int = 5,
    reset_frequency: str = NumberSequence.RESET_NEVER,
    actor: Any = None,
    current_date: datetime.date | None = None,
) -> str:
    """Generate the next sequential document number atomically for an organization."""
    # Row lock using unscoped manager to avoid ambient tenant context dependency
    seq = (
        NumberSequence.all_tenants.select_for_update()
        .filter(organization_id=organization_id, name=name)
        .first()
    )

    now = current_date or timezone.now().date()

    if seq is None:
        seq = NumberSequence.all_tenants.create(
            organization_id=organization_id,
            name=name,
            prefix=prefix,
            suffix=suffix,
            padding=padding,
            reset_frequency=reset_frequency,
            next_number=1,
            last_reset_date=now,
            created_by=actor if getattr(actor, "is_authenticated", False) else None,
        )
    else:
        # Check reset logic
        should_reset = False
        if seq.reset_frequency == NumberSequence.RESET_YEARLY:
            if seq.last_reset_date is None or seq.last_reset_date.year != now.year:
                should_reset = True
        elif seq.reset_frequency == NumberSequence.RESET_MONTHLY and (
            seq.last_reset_date is None
            or (seq.last_reset_date.year, seq.last_reset_date.month) != (now.year, now.month)
        ):
            should_reset = True

        if should_reset:
            seq.next_number = 1
            seq.last_reset_date = now

    num_str = str(seq.next_number).zfill(seq.padding)
    formatted = f"{seq.prefix}{num_str}{seq.suffix}"

    seq.next_number += 1
    seq.save(update_fields=["next_number", "last_reset_date", "updated_at"])

    return formatted
