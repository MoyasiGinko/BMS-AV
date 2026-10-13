"""Comprehensive integration tests for Notifications Center, User Preferences, Delivery, and Isolation."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core import notifications, selectors, services, tasks
from apps.core.models import Notification, NotificationChannel, NotificationStatus
from apps.tenancy.models import Membership, NotificationPreference, Organization, Role

User = get_user_model()


@pytest.fixture
def org_owner(db: None) -> tuple[Organization, Any]:
    """Create primary test organization with an owner user."""
    uid = uuid.uuid4().hex[:6]
    org = Organization.objects.create(name=f"Notify Org {uid}", slug=f"notify-org-{uid}")
    user = User.objects.create_user(
        email=f"owner_{uid}@example.com",
        password="ValidPassword123!",
    )
    role = Role.objects.create(
        organization=org,
        name="Owner",
        permissions=["*"],
    )
    Membership.objects.create(organization=org, user=user, role=role, is_owner=True)
    return org, user


@pytest.fixture
def team_member(db: None, org_owner: tuple[Organization, Any]) -> Any:
    """Create a second team member in the primary organization."""
    org, _ = org_owner
    uid = uuid.uuid4().hex[:6]
    user = User.objects.create_user(
        email=f"member_{uid}@example.com",
        password="ValidPassword123!",
    )
    role = Role.objects.create(
        organization=org,
        name="Staff",
        permissions=["sales.view"],
    )
    Membership.objects.create(organization=org, user=user, role=role)
    return user


@pytest.fixture
def other_org_user(db: None) -> tuple[Organization, Any]:
    """Create a separate tenant organization and user for isolation tests."""
    uid = uuid.uuid4().hex[:6]
    org = Organization.objects.create(name=f"Other Org {uid}", slug=f"other-org-{uid}")
    user = User.objects.create_user(
        email=f"other_{uid}@example.com",
        password="ValidPassword123!",
    )
    role = Role.objects.create(
        organization=org,
        name="Owner",
        permissions=["*"],
    )
    Membership.objects.create(organization=org, user=user, role=role, is_owner=True)
    return org, user


@pytest.mark.django_db
class TestNotificationDeliveryAndPreferences:
    """Unit tests for notification delivery, channel routing, and preference resolution."""

    def test_in_app_notification_creation_and_delivery(self, org_owner: tuple[Organization, Any]) -> None:
        org, user = org_owner
        notif = notifications.send_notification(
            organization_id=org.pk,
            category="approvals",
            title="PO #1001 requires approval",
            body="Purchase order for $5,000 exceeds single-signature threshold.",
            channel=NotificationChannel.IN_APP,
            recipient_user=user,
            metadata={"action_url": "/approvals/inbox/1001/", "document_id": 1001},
        )

        assert notif.pk is not None
        assert notif.status == NotificationStatus.SENT
        assert notif.is_read is False
        assert notif.action_url == "/approvals/inbox/1001/"
        assert notif.recipient_user == user
        assert notif.recipient_email == user.email

        # Verify selectors
        unread_count = selectors.get_unread_notifications_count(organization_id=org.pk, user=user)
        assert unread_count == 1

        user_notifications = list(selectors.list_user_notifications(organization_id=org.pk, user=user))
        assert len(user_notifications) == 1
        assert user_notifications[0].public_id == notif.public_id

    def test_email_notification_delivery_via_fake_adapter(self, org_owner: tuple[Organization, Any]) -> None:
        org, user = org_owner
        adapter = notifications.FakeEmailAdapter()
        adapter.clear()
        notifications.set_email_adapter(adapter)

        notif = notifications.send_notification(
            organization_id=org.pk,
            category="billing",
            title="Invoice INV-2026-001 Generated",
            body="Your subscription invoice for October has been generated.",
            channel=NotificationChannel.EMAIL,
            recipient_user=user,
        )

        assert notif.status == NotificationStatus.SENT
        assert len(adapter.outbox) == 1
        record = adapter.outbox[0]
        assert record.subject == "Invoice INV-2026-001 Generated"
        assert user.email in record.recipient_list

    def test_notify_user_helper_dispatches_both_channels(self, org_owner: tuple[Organization, Any]) -> None:
        org, user = org_owner
        adapter = notifications.FakeEmailAdapter()
        adapter.clear()
        notifications.set_email_adapter(adapter)

        results = services.notify_user(
            organization_id=org.pk,
            user=user,
            category="security",
            title="New device login detected",
            body="A login from Chrome on Windows was logged.",
            action_url="/settings/security/",
        )

        assert len(results) == 2
        channels = {r.channel for r in results}
        assert NotificationChannel.IN_APP in channels
        assert NotificationChannel.EMAIL in channels
        assert len(adapter.outbox) == 1

    def test_two_tier_preference_resolution(self, org_owner: tuple[Organization, Any]) -> None:
        org, user = org_owner
        adapter = notifications.FakeEmailAdapter()
        adapter.clear()
        notifications.set_email_adapter(adapter)

        # 1. User disables email for 'inventory'
        services.update_user_notification_preference(
            organization_id=org.pk,
            user=user,
            category="inventory",
            channel=NotificationChannel.EMAIL,
            is_enabled=False,
            actor=user,
        )

        # Dispatch inventory alert
        notifs = services.notify_user(
            organization_id=org.pk,
            user=user,
            category="inventory",
            title="Stock level warning",
            body="Item Widget-X is below minimum quantity.",
        )

        in_app_notif = next(n for n in notifs if n.channel == NotificationChannel.IN_APP)
        email_notif = next(n for n in notifs if n.channel == NotificationChannel.EMAIL)

        assert in_app_notif.status == NotificationStatus.SENT
        assert email_notif.status == NotificationStatus.SKIPPED
        assert len(adapter.outbox) == 0

        # 2. Org disables 'inventory' across the board
        NotificationPreference.objects.create(
            organization=org,
            category="inventory",
            channel=NotificationChannel.IN_APP,
            is_enabled=False,
        )

        # Dispatch again - now in_app is also skipped due to org policy
        notifs2 = services.notify_user(
            organization_id=org.pk,
            user=user,
            category="inventory",
            title="Stock level warning 2",
            body="Item Widget-Y is below minimum quantity.",
        )
        in_app_notif2 = next(n for n in notifs2 if n.channel == NotificationChannel.IN_APP)
        assert in_app_notif2.status == NotificationStatus.SKIPPED

    def test_mark_notification_read_and_unread(self, org_owner: tuple[Organization, Any]) -> None:
        org, user = org_owner
        notif = notifications.send_notification(
            organization_id=org.pk,
            category="approvals",
            title="Approval required",
            body="Review needed",
            channel=NotificationChannel.IN_APP,
            recipient_user=user,
        )

        assert notif.status == NotificationStatus.SENT
        assert selectors.get_unread_notifications_count(organization_id=org.pk, user=user) == 1

        # Mark read
        read_notif = services.mark_notification_read(
            notification_id=str(notif.public_id),
            organization_id=org.pk,
            user=user,
        )
        assert read_notif is not None
        assert read_notif.status == NotificationStatus.READ
        assert read_notif.read_at is not None
        assert read_notif.is_read is True
        assert selectors.get_unread_notifications_count(organization_id=org.pk, user=user) == 0

        # Mark unread
        unread_notif = services.mark_notification_unread(
            notification_id=str(notif.public_id),
            organization_id=org.pk,
            user=user,
        )
        assert unread_notif is not None
        assert unread_notif.status == NotificationStatus.SENT
        assert unread_notif.read_at is None
        assert unread_notif.is_read is False
        assert selectors.get_unread_notifications_count(organization_id=org.pk, user=user) == 1

    def test_mark_all_notifications_read(self, org_owner: tuple[Organization, Any]) -> None:
        org, user = org_owner
        for idx in range(4):
            notifications.send_notification(
                organization_id=org.pk,
                category="sales",
                title=f"New Sale #{idx}",
                body=f"Sale order #{idx} has been recorded.",
                channel=NotificationChannel.IN_APP,
                recipient_user=user,
            )

        assert selectors.get_unread_notifications_count(organization_id=org.pk, user=user) == 4

        count = services.mark_all_notifications_read(
            organization_id=org.pk,
            user=user,
        )
        assert count == 4
        assert selectors.get_unread_notifications_count(organization_id=org.pk, user=user) == 0

    def test_delete_notification(self, org_owner: tuple[Organization, Any]) -> None:
        org, user = org_owner
        notif = notifications.send_notification(
            organization_id=org.pk,
            category="system",
            title="Temporary alert",
            body="To be deleted",
            channel=NotificationChannel.IN_APP,
            recipient_user=user,
        )

        deleted = services.delete_notification(
            organization_id=org.pk,
            notification_id=str(notif.public_id),
            user=user,
        )
        assert deleted is True
        found = selectors.get_notification_by_id(
            organization_id=org.pk,
            notification_id=str(notif.public_id),
        )
        assert found is None


@pytest.mark.django_db
class TestNotificationTenantAndUserIsolation:
    """Security tests verifying strict isolation between tenants and individual users."""

    def test_cross_tenant_isolation(
        self,
        org_owner: tuple[Organization, Any],
        other_org_user: tuple[Organization, Any],
    ) -> None:
        org_a, user_a = org_owner
        org_b, user_b = other_org_user

        notif_a = notifications.send_notification(
            organization_id=org_a.pk,
            category="billing",
            title="Tenant A Private Alert",
            body="Confidential invoice details",
            channel=NotificationChannel.IN_APP,
            recipient_user=user_a,
        )

        # User B in Org B queries list_user_notifications
        notifs_b = list(selectors.list_user_notifications(organization_id=org_b.pk, user=user_b))
        assert not any(n.public_id == notif_a.public_id for n in notifs_b)

        # User B cannot mark User A's notification as read
        read_res = services.mark_notification_read(
            notification_id=str(notif_a.public_id),
            organization_id=org_b.pk,
            user=user_b,
        )
        assert read_res is None

        # User B cannot delete User A's notification
        del_res = services.delete_notification(
            organization_id=org_b.pk,
            notification_id=str(notif_a.public_id),
            user=user_b,
        )
        assert del_res is False

        # Confirm notif_a is untouched
        refetched = selectors.get_notification_by_id(
            organization_id=org_a.pk,
            notification_id=str(notif_a.public_id),
        )
        assert refetched is not None
        assert refetched.status == NotificationStatus.SENT

    def test_cross_user_isolation_within_same_tenant(
        self,
        org_owner: tuple[Organization, Any],
        team_member: Any,
    ) -> None:
        org, user_a = org_owner
        user_b = team_member

        notif_a = notifications.send_notification(
            organization_id=org.pk,
            category="security",
            title="Personal confidential alert for User A",
            body="Reset PIN requested",
            channel=NotificationChannel.IN_APP,
            recipient_user=user_a,
        )

        # Member B checks their notifications
        member_notifs = list(selectors.list_user_notifications(organization_id=org.pk, user=user_b))
        assert not any(n.public_id == notif_a.public_id for n in member_notifs)

        # Member B cannot mark read User A's notification
        read_attempt = services.mark_notification_read(
            notification_id=str(notif_a.public_id),
            organization_id=org.pk,
            user=user_b,
        )
        assert read_attempt is None


@pytest.mark.django_db
class TestNotificationWebViewsAndHTMX:
    """End-to-end tests for web UI views and HTMX partial endpoints."""

    def test_notification_center_and_tabs(self, org_owner: tuple[Organization, Any]) -> None:
        org, user = org_owner
        client = Client()
        client.force_login(user)

        # Create 1 read, 1 unread notification
        notifications.send_notification(
            organization_id=org.pk,
            category="billing",
            title="Unread Billing Alert",
            body="Payment due soon",
            channel=NotificationChannel.IN_APP,
            recipient_user=user,
        )
        n2 = notifications.send_notification(
            organization_id=org.pk,
            category="approvals",
            title="Archived Approval Alert",
            body="Approved by manager",
            channel=NotificationChannel.IN_APP,
            recipient_user=user,
        )
        services.mark_notification_read(notification_id=str(n2.public_id), organization_id=org.pk, user=user)

        # GET /notifications/
        res = client.get("/notifications/", HTTP_X_ORGANIZATION_ID=str(org.public_id))
        assert res.status_code == 200
        content = res.content.decode("utf-8")
        assert "Notifications Center" in content
        assert "Unread Billing Alert" in content
        assert "Archived Approval Alert" in content

        # Filter by tab=unread
        res_unread = client.get("/notifications/?tab=unread", HTTP_X_ORGANIZATION_ID=str(org.public_id))
        assert res_unread.status_code == 200
        content_unread = res_unread.content.decode("utf-8")
        assert "Unread Billing Alert" in content_unread
        assert "Archived Approval Alert" not in content_unread

        # Filter by category=approvals
        res_cat = client.get("/notifications/?category=approvals", HTTP_X_ORGANIZATION_ID=str(org.public_id))
        assert res_cat.status_code == 200
        content_cat = res_cat.content.decode("utf-8")
        assert "Archived Approval Alert" in content_cat
        assert "Unread Billing Alert" not in content_cat

    def test_unread_count_badge_and_preview_htmx(self, org_owner: tuple[Organization, Any]) -> None:
        org, user = org_owner
        client = Client()
        client.force_login(user)

        # When 0 notifications
        res_badge = client.get("/notifications/unread-count/", HTTP_X_ORGANIZATION_ID=str(org.public_id))
        assert res_badge.status_code == 200
        assert "hidden" in res_badge.content.decode("utf-8")

        # Create unread notification
        notif = notifications.send_notification(
            organization_id=org.pk,
            category="sales",
            title="Big deal closed",
            body="$25,000 deal",
            channel=NotificationChannel.IN_APP,
            recipient_user=user,
        )

        res_badge2 = client.get("/notifications/unread-count/", HTTP_X_ORGANIZATION_ID=str(org.public_id))
        assert res_badge2.status_code == 200
        assert "1" in res_badge2.content.decode("utf-8")

        # Preview dropdown
        res_prev = client.get("/notifications/preview/", HTTP_X_ORGANIZATION_ID=str(org.public_id))
        assert res_prev.status_code == 200
        assert "Big deal closed" in res_prev.content.decode("utf-8")

        # Mark read via HTMX
        res_mark = client.post(
            f"/notifications/{notif.public_id}/read/",
            HTTP_HX_REQUEST="true",
            HTTP_X_ORGANIZATION_ID=str(org.public_id),
        )
        assert res_mark.status_code == 200
        assert res_mark.headers.get("HX-Trigger") == "refreshUnreadCount"

    def test_user_preferences_screen(self, org_owner: tuple[Organization, Any]) -> None:
        org, user = org_owner
        client = Client()
        client.force_login(user)

        # GET preferences
        res = client.get("/notifications/preferences/", HTTP_X_ORGANIZATION_ID=str(org.public_id))
        assert res.status_code == 200
        assert "Personal Notification Preferences" in res.content.decode("utf-8")

        # POST update preferences: enable approvals email, disable billing in_app
        post_data = {
            "approvals_email": "on",
            "approvals_in_app": "on",
            "billing_email": "on",
            # billing_in_app left off
        }
        res_post = client.post(
            "/notifications/preferences/",
            data=post_data,
            HTTP_X_ORGANIZATION_ID=str(org.public_id),
        )
        assert res_post.status_code == 302
        assert res_post.url == "/notifications/preferences/"

        prefs_map = selectors.get_user_notification_preferences_map(
            organization_id=org.pk,
            user_id=user.pk,
        )
        assert prefs_map.get(("approvals", "email")) is True
        assert prefs_map.get(("billing", "in_app")) is False


@pytest.mark.django_db
class TestNotificationRESTAPI:
    """Tests for DRF REST API endpoints under /api/v1/core/notifications/."""

    def test_list_notifications_and_unread_count(self, org_owner: tuple[Organization, Any]) -> None:
        org, user = org_owner
        client = APIClient()
        client.force_authenticate(user=user)

        # Create notifications
        notifications.send_notification(
            organization_id=org.pk,
            category="payroll",
            title="Payslip Released",
            body="Your monthly payslip is ready.",
            channel=NotificationChannel.IN_APP,
            recipient_user=user,
        )

        res = client.get(
            "/api/v1/core/notifications/",
            HTTP_X_ORGANIZATION_ID=str(org.public_id),
        )
        assert res.status_code == 200
        data = res.json()
        items = data.get("results", data)
        assert len(items) == 1
        assert items[0]["title"] == "Payslip Released"

        # Check unread count
        res_count = client.get(
            "/api/v1/core/notifications/unread-count/",
            HTTP_X_ORGANIZATION_ID=str(org.public_id),
        )
        assert res_count.status_code == 200
        assert res_count.json()["unread_count"] == 1

    def test_api_mark_read_and_preferences(self, org_owner: tuple[Organization, Any]) -> None:
        org, user = org_owner
        client = APIClient()
        client.force_authenticate(user=user)

        notif = notifications.send_notification(
            organization_id=org.pk,
            category="billing",
            title="Invoice Alert",
            body="Invoice #1234",
            channel=NotificationChannel.IN_APP,
            recipient_user=user,
        )

        # Mark read
        res_read = client.post(
            f"/api/v1/core/notifications/{notif.public_id}/mark-read/",
            HTTP_X_ORGANIZATION_ID=str(org.public_id),
        )
        assert res_read.status_code == 200
        assert res_read.json()["is_read"] is True

        # Preferences GET
        res_pref = client.get(
            "/api/v1/core/notifications/preferences/",
            HTTP_X_ORGANIZATION_ID=str(org.public_id),
        )
        assert res_pref.status_code == 200
        pref_items = res_pref.json()
        assert len(pref_items) > 0

        # Preferences POST
        update_payload = {
            "preferences": [
                {"category": "approvals", "channel": "email", "is_enabled": False},
                {"category": "approvals", "channel": "in_app", "is_enabled": True},
            ]
        }
        res_update = client.post(
            "/api/v1/core/notifications/preferences/",
            data=update_payload,
            format="json",
            HTTP_X_ORGANIZATION_ID=str(org.public_id),
        )
        assert res_update.status_code == 200
        updated = res_update.json()
        approvals_email = next(p for p in updated if p["category"] == "approvals" and p["channel"] == "email")
        assert approvals_email["is_enabled"] is False


@pytest.mark.django_db
class TestNotificationBackgroundTasks:
    """Tests for Celery asynchronous delivery and cleanup jobs."""

    def test_send_async_notification_task(self, org_owner: tuple[Organization, Any]) -> None:
        org, user = org_owner
        notif_id = tasks.send_async_notification(
            organization_id=org.pk,
            category="approvals",
            title="Background Task Alert",
            body="Task completed successfully",
            channel="in_app",
            recipient_user_id=user.pk,
        )

        assert notif_id is not None
        notif = Notification.all_tenants.filter(public_id=notif_id).first()
        assert notif is not None
        assert notif.title == "Background Task Alert"

    def test_cleanup_old_notifications_task(self, org_owner: tuple[Organization, Any]) -> None:
        org, user = org_owner
        notif = notifications.send_notification(
            organization_id=org.pk,
            category="system",
            title="Old notification",
            body="Purge me",
            channel=NotificationChannel.IN_APP,
            recipient_user=user,
        )
        services.mark_notification_read(notification=notif, user=user)

        # Backdate created_at to 100 days ago
        old_time = timezone.now() - datetime.timedelta(days=100)
        Notification.all_tenants.filter(pk=notif.pk).update(created_at=old_time)

        deleted = tasks.cleanup_old_notifications(days=90)
        assert deleted == 1
        assert Notification.all_tenants.filter(pk=notif.pk).exists() is False
