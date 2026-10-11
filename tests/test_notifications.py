"""Integration tests for Core Email Adapters and Notification Framework across tenancy and preferences."""

from __future__ import annotations

from typing import Any

import pytest

from apps.accounts.models import User
from apps.billing.services import seed_default_plans
from apps.core import notifications
from apps.core.models import NotificationChannel, NotificationStatus
from apps.tenancy.models import NotificationPreference
from apps.tenancy.services import provision_organization


@pytest.fixture
def notif_setup(db: None) -> dict[str, Any]:
    seed_default_plans()
    admin_user = User.objects.create_user(email="notif_admin@example.com", password="Password123!")
    org = provision_organization(
        name="Notification Test Org",
        slug="notif-test-org",
        owner=admin_user,
        plan="starter",
    )
    return {"admin_user": admin_user, "org": org}


def test_fake_email_adapter_recording_and_clearing() -> None:
    """Verify FakeEmailAdapter records dispatched emails into in-memory outbox."""
    adapter = notifications.FakeEmailAdapter()
    adapter.clear()
    assert len(adapter.outbox) == 0

    success = adapter.send_mail(
        subject="Welcome to Business OS",
        message="Hello World!",
        recipient_list=["client@example.com"],
        from_email="no-reply@bos.local",
    )

    assert success is True
    assert len(adapter.outbox) == 1
    record = adapter.outbox[0]
    assert record.subject == "Welcome to Business OS"
    assert "client@example.com" in record.to


def test_send_notification_lifecycle(notif_setup: dict[str, Any]) -> None:
    """Verify notification record creation, fake email dispatch, and read status."""
    org = notif_setup["org"]
    user = notif_setup["admin_user"]

    adapter = notifications.FakeEmailAdapter()
    adapter.clear()
    notifications.set_email_adapter(adapter)

    notif = notifications.send_notification(
        organization_id=org.pk,
        category="sales.invoice",
        title="Invoice INV-2026-0001",
        body="Your invoice is ready for payment.",
        recipient_email="customer@example.com",
        recipient_user=user,
        channel=NotificationChannel.EMAIL,
        actor=user,
    )

    assert notif.pk is not None
    assert notif.status == NotificationStatus.SENT
    assert len(adapter.outbox) == 1
    assert adapter.outbox[0].subject == "Invoice INV-2026-0001"

    notifications.mark_notification_read(notification=notif, read_by=user)
    notif.refresh_from_db()
    assert notif.status == NotificationStatus.READ
    assert notif.read_at is not None


def test_send_notification_respects_tenant_preferences(notif_setup: dict[str, Any]) -> None:
    """Verify notification is suppressed when tenant preference disables the category."""
    org = notif_setup["org"]
    user = notif_setup["admin_user"]

    adapter = notifications.FakeEmailAdapter()
    adapter.clear()
    notifications.set_email_adapter(adapter)

    # Disable category
    NotificationPreference.all_tenants.create(
        organization=org,
        channel=NotificationChannel.EMAIL,
        category="sales.invoice",
        is_enabled=False,
    )

    notif = notifications.send_notification(
        organization_id=org.pk,
        category="sales.invoice",
        title="Suppressed Notification",
        body="This should not be sent",
        recipient_email="customer@example.com",
        actor=user,
    )

    assert notif.status == NotificationStatus.SKIPPED
    assert len(adapter.outbox) == 0
