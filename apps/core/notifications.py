"""Email adapter and notification framework for Business OS."""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from django.apps import apps
from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Q
from django.utils import timezone

from apps.core.events import DomainEvent, publish
from apps.core.models import Notification, NotificationChannel, NotificationStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NotificationSentEvent(DomainEvent):
    """Domain event published when a notification record is sent."""

    event_type: str = "core.notification.sent"
    notification_id: str = ""
    recipient: str = ""
    category: str = ""
    channel: str = ""


@runtime_checkable
class EmailAdapter(Protocol):
    """Protocol defining the transactional email delivery interface."""

    def send_mail(
        self,
        *,
        subject: str,
        message: str,
        recipient_list: list[str],
        from_email: str | None = None,
        html_message: str | None = None,
        fail_silently: bool = False,
    ) -> bool:
        """Send an email and return True on success, False on failure."""
        ...


class SmtpEmailAdapter:
    """Production email adapter delivering messages via Django mailers / SMTP."""

    def send_mail(
        self,
        *,
        subject: str,
        message: str,
        recipient_list: list[str],
        from_email: str | None = None,
        html_message: str | None = None,
        fail_silently: bool = False,
    ) -> bool:
        from_addr = from_email or getattr(settings, "DEFAULT_FROM_EMAIL", "notifications@businessos.local")
        try:
            sent_count = send_mail(
                subject=subject,
                message=message,
                from_email=from_addr,
                recipient_list=recipient_list,
                html_message=html_message,
                fail_silently=fail_silently,
            )
            return sent_count > 0
        except Exception as exc:
            logger.exception("SmtpEmailAdapter failed to deliver email to %s: %s", recipient_list, exc)
            if not fail_silently:
                raise
            return False

    def clear(self) -> None:
        """No-op clear for adapter interface compatibility."""
        pass


@dataclass
class SentEmailRecord:
    """In-memory record of an email dispatched by FakeEmailAdapter."""

    subject: str
    message: str
    recipient_list: list[str]
    from_email: str
    html_message: str | None = None
    sent_at: datetime = field(default_factory=timezone.now)

    @property
    def to(self) -> list[str]:
        return self.recipient_list


class FakeEmailAdapter:
    """Sandbox in-memory email adapter for tests, CI, and local dev without SMTP credentials."""

    outbox: list[SentEmailRecord] = []

    def send_mail(
        self,
        *,
        subject: str,
        message: str,
        recipient_list: list[str],
        from_email: str | None = None,
        html_message: str | None = None,
        fail_silently: bool = False,
    ) -> bool:
        from_addr = from_email or getattr(settings, "DEFAULT_FROM_EMAIL", "notifications@businessos.local")
        record = SentEmailRecord(
            subject=subject,
            message=message,
            recipient_list=list(recipient_list),
            from_email=from_addr,
            html_message=html_message,
            sent_at=timezone.now(),
        )
        self.outbox.append(record)
        logger.info(
            "FakeEmailAdapter recorded email to %s: '%s' (total outbox: %d)",
            recipient_list,
            subject,
            len(self.outbox),
        )
        return True

    @classmethod
    def clear(cls) -> None:
        """Clear all messages from the in-memory outbox."""
        cls.outbox.clear()

    @classmethod
    def get_sent_emails(cls) -> list[SentEmailRecord]:
        """Return shallow copy of recorded emails."""
        return list(cls.outbox)

    @classmethod
    def find_email(
        cls,
        *,
        recipient: str | None = None,
        subject_contains: str | None = None,
    ) -> SentEmailRecord | None:
        """Find the latest recorded email matching the given recipient or subject substring."""
        for email in reversed(cls.outbox):
            if recipient and recipient not in email.recipient_list:
                continue
            if subject_contains and subject_contains not in email.subject:
                continue
            return email
        return None


class _AdapterRegistry:
    active: EmailAdapter | None = None


def get_email_adapter() -> EmailAdapter:
    """Return the configured email adapter (FakeEmailAdapter in test/sandbox, SmtpEmailAdapter in prod)."""
    if _AdapterRegistry.active is not None:
        return _AdapterRegistry.active

    adapter_name = getattr(settings, "NOTIFICATION_EMAIL_ADAPTER", None)
    if adapter_name == "smtp":
        _AdapterRegistry.active = SmtpEmailAdapter()
    elif (
        adapter_name == "fake"
        or settings.DEBUG
        or getattr(settings, "IS_TEST", False)
        or "pytest" in sys.modules
    ):
        _AdapterRegistry.active = FakeEmailAdapter()
    else:
        # Default to SmtpEmailAdapter in production, FakeEmailAdapter in local/test
        _AdapterRegistry.active = FakeEmailAdapter() if settings.DEBUG else SmtpEmailAdapter()

    return _AdapterRegistry.active


def set_email_adapter(adapter: EmailAdapter | None) -> None:
    """Explicitly override the active email adapter (primarily for unit tests)."""
    _AdapterRegistry.active = adapter


def is_notification_enabled(*, organization_id: int, category: str, channel: str) -> bool:
    """Check tenant NotificationPreference for category and channel."""
    try:
        pref_model = apps.get_model("tenancy", "NotificationPreference")
        if pref_model:
            # Match exact category or without module prefix / plurals
            clean_cat = category.rsplit(".", maxsplit=1)[-1]
            cat_query = Q(category=category) | Q(category=clean_cat)
            if not clean_cat.endswith("s"):
                cat_query |= Q(category=f"{clean_cat}s")
            elif clean_cat.endswith("s"):
                cat_query |= Q(category=clean_cat[:-1])

            pref = (
                pref_model.all_tenants.filter(organization_id=organization_id, channel=channel)
                .filter(cat_query)
                .first()
            )
            if pref is not None:
                return pref.is_enabled
    except Exception as exc:
        logger.debug("Failed querying NotificationPreference: %s", exc)
    return True


def send_notification(
    *,
    organization_id: int,
    category: str,
    title: str,
    body: str,
    channel: str = NotificationChannel.EMAIL,
    recipient_email: str = "",
    recipient_user: Any = None,
    metadata: dict[str, Any] | None = None,
    actor: Any = None,
) -> Notification:
    """Create a Notification record, check tenant preferences, and deliver via adapter."""
    enabled = is_notification_enabled(
        organization_id=organization_id,
        category=category,
        channel=channel,
    )

    recipient_addr = recipient_email
    if not recipient_addr and recipient_user and getattr(recipient_user, "email", None):
        recipient_addr = recipient_user.email

    notification = Notification.objects.create(
        organization_id=organization_id,
        recipient_user=recipient_user,
        recipient_email=recipient_addr,
        channel=channel,
        category=category,
        title=title,
        body=body,
        metadata=metadata or {},
        status=NotificationStatus.SKIPPED if not enabled else NotificationStatus.PENDING,
        error_message="Notification preference disabled by tenant." if not enabled else "",
        created_by=actor,
    )

    if not enabled:
        return notification

    # Deliver based on channel
    if channel == NotificationChannel.EMAIL:
        if not recipient_addr:
            notification.status = NotificationStatus.FAILED
            notification.error_message = "No recipient email address specified."
            notification.save(update_fields=["status", "error_message", "updated_at"])
            return notification

        adapter = get_email_adapter()
        try:
            delivered = adapter.send_mail(
                subject=title,
                message=body,
                recipient_list=[recipient_addr],
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "notifications@businessos.local"),
                fail_silently=False,
            )
            if delivered:
                notification.status = NotificationStatus.SENT
                notification.sent_at = timezone.now()
            else:
                notification.status = NotificationStatus.FAILED
                notification.error_message = "Email adapter returned delivery failure."
        except Exception as exc:
            notification.status = NotificationStatus.FAILED
            notification.error_message = str(exc)[:500]
        notification.save(update_fields=["status", "sent_at", "error_message", "updated_at"])

    elif channel == NotificationChannel.IN_APP:
        # In-app notifications are stored pending user read
        notification.status = NotificationStatus.SENT
        notification.sent_at = timezone.now()
        notification.save(update_fields=["status", "sent_at", "updated_at"])

    publish(
        NotificationSentEvent(
            organization_id=organization_id,
            notification_id=str(notification.public_id),
            recipient=recipient_addr,
            category=category,
            channel=channel,
        )
    )
    return notification


def mark_notification_read(
    *,
    notification: Notification | None = None,
    notification_id: str | None = None,
    organization_id: int | None = None,
    read_by: Any = None,
) -> Notification | None:
    """Mark a notification as read by the recipient."""
    if notification is not None:
        notification.status = NotificationStatus.READ
        notification.read_at = timezone.now()
        notification.save(update_fields=["status", "read_at", "updated_at"])
        return notification

    if notification_id and organization_id:
        notif = Notification.all_tenants.filter(
            public_id=notification_id,
            organization_id=organization_id,
        ).first()
        if notif:
            notif.status = NotificationStatus.READ
            notif.read_at = timezone.now()
            notif.save(update_fields=["status", "read_at", "updated_at"])
            return notif
    return None
