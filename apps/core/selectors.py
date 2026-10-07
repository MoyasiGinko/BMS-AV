"""Core selectors for reading NumberSequence and shared entities."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.core.models import NumberSequence


def get_number_sequence(*, organization_id: int, name: str) -> NumberSequence | None:
    return NumberSequence.all_tenants.filter(organization_id=organization_id, name=name).first()


def list_number_sequences(*, organization_id: int) -> QuerySet[NumberSequence]:
    return NumberSequence.all_tenants.filter(organization_id=organization_id).order_by("name")
