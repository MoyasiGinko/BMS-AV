"""Core selectors for reading NumberSequence and shared entities."""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet

from apps.core.models import ApiKey, NumberSequence


def get_number_sequence(*, organization_id: int, name: str) -> NumberSequence | None:
    return NumberSequence.all_tenants.filter(organization_id=organization_id, name=name).first()


def list_number_sequences(*, organization_id: int) -> QuerySet[NumberSequence]:
    return NumberSequence.all_tenants.filter(organization_id=organization_id).order_by("name")


def get_api_key_by_id(*, organization_id: int, api_key_id: Any) -> ApiKey | None:
    """Fetch an API key by PK or public_id within an organization."""
    qs = ApiKey.all_tenants.filter(organization_id=organization_id)
    if isinstance(api_key_id, int) or (isinstance(api_key_id, str) and api_key_id.isdigit()):
        return qs.filter(pk=int(api_key_id)).first()
    return qs.filter(public_id=api_key_id).first()


def get_active_api_key_by_prefix(*, prefix: str) -> ApiKey | None:
    """Fast indexed prefix lookup for active, non-revoked API key."""
    return (
        ApiKey.all_tenants.select_related("organization", "user", "created_by")
        .filter(prefix=prefix, is_active=True, revoked_at__isnull=True)
        .first()
    )


def list_organization_api_keys(*, organization_id: int, include_revoked: bool = False) -> QuerySet[ApiKey]:
    """Return all API keys for an organization ordered by newest first."""
    qs = ApiKey.all_tenants.filter(organization_id=organization_id).select_related(
        "user", "created_by", "rotated_from"
    )
    if not include_revoked:
        qs = qs.filter(is_active=True, revoked_at__isnull=True)
    return qs.order_by("-created_at")
