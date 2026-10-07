"""Core services for number sequences and shared cross-domain logic."""

from __future__ import annotations

import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.core.events import publish
from apps.core.exceptions import ValidationError
from apps.core.models import AuditLog, NumberSequence
from apps.core.tenant_context import get_current_organization_id


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


@transaction.atomic
def record_audit_log(
    *,
    action: str,
    organization_id: int | None = None,
    target: Any = None,
    changes: dict[str, Any] | None = None,
    actor: Any = None,
    ip_address: str | None = None,
    user_agent: str = "",
) -> AuditLog:
    """Record an immutable audit log entry and publish audit.logged domain event."""
    org_id = organization_id or get_current_organization_id()
    if org_id is None:
        raise ValidationError("organization_id is required for audit logs.")

    target_type = ""
    target_id = ""
    object_repr = ""
    if target is not None:
        target_type = f"{target.__class__.__module__}.{target.__class__.__name__}"
        target_id = str(getattr(target, "pk", getattr(target, "id", "")))
        object_repr = str(target)[:255]

    audit = AuditLog.all_tenants.create(
        organization_id=org_id,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        object_repr=object_repr,
        changes=changes or {},
        ip_address=ip_address,
        user_agent=user_agent,
    )

    publish(
        "audit.logged",
        payload={
            "audit_id": str(audit.public_id),
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
        },
        organization_id=org_id,
        actor_id=getattr(actor, "pk", None) if getattr(actor, "is_authenticated", False) else None,
    )

    return audit
