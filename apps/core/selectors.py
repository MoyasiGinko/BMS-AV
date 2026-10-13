"""Core selectors for reading NumberSequence and shared entities."""

from __future__ import annotations

from typing import Any

from django.apps import apps
from django.db.models import Q, QuerySet

from apps.core.models import ApiKey, Notification, NotificationChannel, NotificationStatus, NumberSequence


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


def list_user_notifications(
    *,
    organization_id: int,
    user: Any,
    status: str | None = None,
    category: str | None = None,
    channel: str | None = None,
    unread_only: bool = False,
) -> QuerySet[Notification]:
    """Return notifications addressed to the user within the organization."""
    user_id = getattr(user, "pk", None)
    user_email = getattr(user, "email", "") or ""

    qs = Notification.all_tenants.filter(organization_id=organization_id)
    if user_id and user_email:
        qs = qs.filter(Q(recipient_user_id=user_id) | Q(recipient_email=user_email))
    elif user_id:
        qs = qs.filter(recipient_user_id=user_id)
    elif user_email:
        qs = qs.filter(recipient_email=user_email)
    else:
        return qs.none()

    if unread_only or status == "unread":
        qs = qs.exclude(status=NotificationStatus.READ)
    elif status:
        qs = qs.filter(status=status)

    if category:
        qs = qs.filter(category=category)
    if channel:
        qs = qs.filter(channel=channel)

    return qs.select_related("recipient_user").order_by("-created_at")


def get_unread_notifications_count(*, organization_id: int, user: Any) -> int:
    """Return count of unread in-app notifications for a user within an organization."""
    user_id = getattr(user, "pk", None)
    user_email = getattr(user, "email", "") or ""
    if not user_id and not user_email:
        return 0

    qs = Notification.all_tenants.filter(
        organization_id=organization_id,
        channel=NotificationChannel.IN_APP,
    ).exclude(status__in=[NotificationStatus.READ, NotificationStatus.SKIPPED])

    if user_id and user_email:
        qs = qs.filter(Q(recipient_user_id=user_id) | Q(recipient_email=user_email))
    elif user_id:
        qs = qs.filter(recipient_user_id=user_id)
    else:
        qs = qs.filter(recipient_email=user_email)

    return qs.count()


def get_notification_by_id(
    *,
    organization_id: int,
    notification_id: Any,
    user: Any | None = None,
) -> Notification | None:
    """Fetch a notification by PK or public_id, optionally ensuring recipient ownership."""
    qs = Notification.all_tenants.filter(organization_id=organization_id)
    if isinstance(notification_id, int) or (isinstance(notification_id, str) and notification_id.isdigit()):
        qs = qs.filter(pk=int(notification_id))
    else:
        qs = qs.filter(public_id=notification_id)

    if user is not None:
        user_id = getattr(user, "pk", None)
        user_email = getattr(user, "email", "") or ""
        if user_id and user_email:
            qs = qs.filter(Q(recipient_user_id=user_id) | Q(recipient_email=user_email))
        elif user_id:
            qs = qs.filter(recipient_user_id=user_id)
        elif user_email:
            qs = qs.filter(recipient_email=user_email)
        else:
            return None

    return qs.select_related("recipient_user").first()


def list_user_notification_preferences(*, organization_id: int, user_id: int) -> QuerySet[Any]:
    """Fetch all personal notification preferences for a user in an organization."""
    user_pref_model = apps.get_model("tenancy", "UserNotificationPreference")
    return user_pref_model.all_tenants.filter(
        organization_id=organization_id,
        user_id=user_id,
    ).order_by("category", "channel")


def get_user_notification_preferences_map(
    *, organization_id: int, user_id: int
) -> dict[tuple[str, str], bool]:
    """Return a lookup dict mapping (category, channel) -> is_enabled for the user."""
    prefs = list_user_notification_preferences(organization_id=organization_id, user_id=user_id)
    return {(p.category, p.channel): p.is_enabled for p in prefs}
