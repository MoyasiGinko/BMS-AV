"""Core services for number sequences and shared cross-domain logic."""

from __future__ import annotations

import datetime
import hashlib
import ipaddress
import secrets
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.core.events import publish
from apps.core.exceptions import ValidationError
from apps.core.metrics import record_metric
from apps.core.models import ApiKey, AuditLog, NumberSequence, VoidDocumentNumber
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
def record_void_document_number(
    *,
    organization_id: int,
    sequence: NumberSequence | None = None,
    sequence_name: str | None = None,
    document_number: str,
    reason: str,
    sequence_number: int | None = None,
    source: str = "",
    actor: Any = None,
) -> VoidDocumentNumber:
    """Record a sequential document number as void or skipped for statutory tracking."""
    if sequence is None:
        if not sequence_name:
            raise ValidationError("Either sequence or sequence_name must be provided.")
        # Scoped to organization using all_tenants for execution outside request thread context
        sequence = (
            NumberSequence.all_tenants.select_for_update()
            .filter(organization_id=organization_id, name=sequence_name)
            .first()
        )
        if sequence is None:
            raise ValidationError(f"Number sequence '{sequence_name}' not found for organization.")

    # Scoped to organization using all_tenants for execution outside request thread context
    void_record, _ = VoidDocumentNumber.all_tenants.get_or_create(
        organization_id=organization_id,
        sequence=sequence,
        document_number=document_number,
        defaults={
            "sequence_number": sequence_number,
            "reason": reason,
            "source": source,
            "actor": actor if getattr(actor, "is_authenticated", False) else None,
            "voided_at": timezone.now(),
        },
    )
    return void_record


def list_void_document_numbers(
    *,
    organization_id: int,
    sequence_name: str | None = None,
) -> Any:
    """List all voided document numbers for an organization, optionally filtered by sequence."""
    # Scoped to organization using all_tenants for execution outside request thread context
    qs = VoidDocumentNumber.all_tenants.filter(organization_id=organization_id)
    if sequence_name:
        qs = qs.filter(sequence__name=sequence_name)
    return qs.order_by("-voided_at")


@transaction.atomic
def detect_and_record_sequence_gaps(
    *,
    organization_id: int,
    sequence: NumberSequence,
    expected_next: int,
    actual_next: int,
    reason: str = "Unbroken sequence gap detected",
    source: str = "",
    actor: Any = None,
) -> list[VoidDocumentNumber]:
    """Detect and record all skipped numbers between expected_next and actual_next - 1 as void."""
    if actual_next <= expected_next:
        return []

    created_voids = []
    for num in range(expected_next, actual_next):
        num_str = str(num).zfill(sequence.padding)
        formatted = f"{sequence.prefix}{num_str}{sequence.suffix}"
        void_entry = record_void_document_number(
            organization_id=organization_id,
            sequence=sequence,
            document_number=formatted,
            sequence_number=num,
            reason=reason,
            source=source,
            actor=actor,
        )
        created_voids.append(void_entry)
    return created_voids


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


# ---------------------------------------------------------------------------
# API Key Management
# ---------------------------------------------------------------------------

AVAILABLE_SCOPES = [
    "admin",
    "settings:read",
    "settings:write",
    "billing:read",
    "billing:write",
    "catalog:read",
    "catalog:write",
    "inventory:read",
    "inventory:write",
    "purchasing:read",
    "purchasing:write",
    "sales:read",
    "sales:write",
    "pos:read",
    "pos:write",
    "customers:read",
    "customers:write",
    "crm:read",
    "crm:write",
    "accounting:read",
    "accounting:write",
    "hr:read",
    "hr:write",
    "payroll:read",
    "payroll:write",
    "reports:read",
    "automation:read",
    "automation:write",
    "integrations:read",
    "integrations:write",
    "ai:read",
    "ai:write",
]


def _generate_api_key_material() -> tuple[str, str, str]:
    prefix_slug = secrets.token_hex(4)
    prefix = f"bos_live_{prefix_slug}"
    secret_slug = secrets.token_hex(24)
    raw_key = f"{prefix}_{secret_slug}"
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return prefix, raw_key, key_hash


def is_ip_allowed(client_ip: str | None, allowlist: list[str]) -> bool:
    if not allowlist:
        return True
    if not client_ip:
        return False
    try:
        ip = ipaddress.ip_address(client_ip)
    except ValueError:
        return False

    for entry in allowlist:
        clean = str(entry).strip()
        if not clean:
            continue
        try:
            if "/" in clean:
                if ip in ipaddress.ip_network(clean, strict=False):
                    return True
            elif ip == ipaddress.ip_address(clean):
                return True
        except ValueError:
            continue
    return False


@transaction.atomic
def create_api_key(
    *,
    organization: Any,
    name: str,
    scopes: list[str] | None = None,
    ip_allowlist: list[str] | None = None,
    expires_at: datetime.datetime | None = None,
    user: Any = None,
    actor: Any = None,
) -> tuple[ApiKey, str]:
    """Create a new hashed API key for a tenant organization. Returns (ApiKey, raw_secret)."""
    clean_name = name.strip()
    if not clean_name:
        raise ValidationError("API key name cannot be empty.")

    prefix, raw_key, key_hash = _generate_api_key_material()
    scopes_list = scopes or ["admin"]
    clean_allowlist = [ip.strip() for ip in (ip_allowlist or []) if ip.strip()]

    for ip_entry in clean_allowlist:
        try:
            if "/" in ip_entry:
                ipaddress.ip_network(ip_entry, strict=False)
            else:
                ipaddress.ip_address(ip_entry)
        except ValueError:
            raise ValidationError(f"Invalid IP address or CIDR range: '{ip_entry}'.") from None

    api_key = ApiKey.all_tenants.create(
        organization=organization,
        name=clean_name,
        prefix=prefix,
        key_hash=key_hash,
        scopes=scopes_list,
        ip_allowlist=clean_allowlist,
        expires_at=expires_at,
        user=user if getattr(user, "is_authenticated", False) else None,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )

    publish(
        "api_key.created",
        payload={
            "api_key_id": str(api_key.public_id),
            "prefix": prefix,
            "name": clean_name,
            "scopes": scopes_list,
        },
        organization_id=organization.pk,
        actor_id=getattr(actor, "pk", None) if getattr(actor, "is_authenticated", False) else None,
    )

    return api_key, raw_key


@transaction.atomic
def rotate_api_key(
    *,
    api_key: ApiKey,
    grace_period_hours: int = 0,
    actor: Any = None,
) -> tuple[ApiKey, str]:
    """Rotate an existing API key, creating a new key with identical configuration."""
    prefix, raw_key, key_hash = _generate_api_key_material()

    new_key = ApiKey.all_tenants.create(
        organization=api_key.organization,
        name=f"{api_key.name} (Rotated)",
        prefix=prefix,
        key_hash=key_hash,
        scopes=list(api_key.scopes),
        ip_allowlist=list(api_key.ip_allowlist),
        expires_at=api_key.expires_at,
        user=api_key.user,
        rotated_from=api_key,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )

    now = timezone.now()
    if grace_period_hours > 0:
        grace_expiry = now + datetime.timedelta(hours=grace_period_hours)
        if api_key.expires_at is None or grace_expiry < api_key.expires_at:
            api_key.expires_at = grace_expiry
        api_key.save(update_fields=["expires_at", "updated_at"])
    else:
        api_key.is_active = False
        api_key.revoked_at = now
        api_key.revoked_by = actor if getattr(actor, "is_authenticated", False) else None
        api_key.save(update_fields=["is_active", "revoked_at", "revoked_by", "updated_at"])

    publish(
        "api_key.rotated",
        payload={
            "old_key_id": str(api_key.public_id),
            "new_key_id": str(new_key.public_id),
            "new_prefix": prefix,
        },
        organization_id=api_key.organization_id,
        actor_id=getattr(actor, "pk", None) if getattr(actor, "is_authenticated", False) else None,
    )

    return new_key, raw_key


@transaction.atomic
def revoke_api_key(
    *,
    api_key: ApiKey,
    actor: Any = None,
) -> ApiKey:
    """Revoke an active API key immediately."""
    api_key.is_active = False
    api_key.revoked_at = timezone.now()
    api_key.revoked_by = actor if getattr(actor, "is_authenticated", False) else None
    api_key.save(update_fields=["is_active", "revoked_at", "revoked_by", "updated_at"])

    publish(
        "api_key.revoked",
        payload={
            "api_key_id": str(api_key.public_id),
            "prefix": api_key.prefix,
        },
        organization_id=api_key.organization_id,
        actor_id=getattr(actor, "pk", None) if getattr(actor, "is_authenticated", False) else None,
    )

    return api_key


@transaction.atomic
def update_api_key(
    *,
    api_key: ApiKey,
    name: str | None = None,
    scopes: list[str] | None = None,
    ip_allowlist: list[str] | None = None,
    expires_at: datetime.datetime | None = None,
    actor: Any = None,
) -> ApiKey:
    """Update non-secret attributes of an API key."""
    update_fields = ["updated_at"]

    if name is not None:
        clean_name = name.strip()
        if not clean_name:
            raise ValidationError("API key name cannot be empty.")
        api_key.name = clean_name
        update_fields.append("name")

    if scopes is not None:
        api_key.scopes = scopes
        update_fields.append("scopes")

    if ip_allowlist is not None:
        clean_allowlist = [ip.strip() for ip in ip_allowlist if ip.strip()]
        for ip_entry in clean_allowlist:
            try:
                if "/" in ip_entry:
                    ipaddress.ip_network(ip_entry, strict=False)
                else:
                    ipaddress.ip_address(ip_entry)
            except ValueError:
                raise ValidationError(f"Invalid IP address or CIDR range: '{ip_entry}'.") from None
        api_key.ip_allowlist = clean_allowlist
        update_fields.append("ip_allowlist")

    if expires_at is not None:
        api_key.expires_at = expires_at
        update_fields.append("expires_at")

    api_key.save(update_fields=update_fields)
    return api_key


def record_api_key_usage(
    *,
    api_key: ApiKey,
    ip_address: str | None = None,
) -> None:
    """Record last-used metadata and increment organization API calls counter."""
    now = timezone.now()
    ApiKey.all_tenants.filter(pk=api_key.pk).update(
        last_used_at=now,
        last_used_ip=ip_address,
    )
    record_metric(api_key.organization_id, "api_calls", 1)


# Notification services re-exported for unified services layer
from apps.core.notifications import (  # noqa: E402
    delete_notification,
    is_notification_enabled,
    mark_all_notifications_read,
    mark_notification_read,
    mark_notification_unread,
    notify_user,
    send_notification,
    update_user_notification_preference,
)

__all__ = [
    "create_api_key",
    "delete_notification",
    "generate_next_number",
    "is_notification_enabled",
    "mark_all_notifications_read",
    "mark_notification_read",
    "mark_notification_unread",
    "notify_user",
    "record_api_key_usage",
    "revoke_api_key",
    "rotate_api_key",
    "send_notification",
    "update_api_key",
    "update_user_notification_preference",
]
