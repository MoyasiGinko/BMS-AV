"""Integration tests for OutboxEvent atomicity, dispatcher idempotency, and AuditLog tenant isolation."""

from __future__ import annotations

import pytest
from django.db import transaction

from apps.accounts.models import User
from apps.core.events import clear_subscribers, publish, subscribe
from apps.core.models import AuditLog, OutboxEvent
from apps.core.services import record_audit_log
from apps.core.tasks import dispatch_outbox_events
from apps.core.tenant_context import get_current_organization_id, tenant_context
from apps.tenancy.models import Branch, Organization


@pytest.mark.django_db
def test_outbox_publish_atomicity_commit_and_rollback() -> None:
    """Verify that OutboxEvent is written atomically: committed with transaction, rolled back on error."""
    org = Organization.objects.create(name="Atomic Corp", slug="atomic-corp")

    # 1. Success case: event commits with the transaction
    with transaction.atomic():
        Branch.all_tenants.create(organization=org, name="Committed Branch", code="C-BR")
        event = publish("branch.created", organization_id=org.id, payload={"branch": "C-BR"})

    assert OutboxEvent.objects.filter(event_id=event.event_id).exists()
    saved = OutboxEvent.objects.get(event_id=event.event_id)
    assert saved.status == OutboxEvent.STATUS_PENDING
    assert saved.organization_id == org.id

    # 2. Rollback case: event must NOT be stored in DB if transaction rolls back
    rolled_back_id = None
    try:
        with transaction.atomic():
            Branch.all_tenants.create(organization=org, name="Failed Branch", code="F-BR")
            evt = publish("branch.created", organization_id=org.id, payload={"branch": "F-BR"})
            rolled_back_id = evt.event_id
            raise RuntimeError("Deliberate failure to trigger rollback")
    except RuntimeError:
        pass

    assert rolled_back_id is not None
    assert not OutboxEvent.objects.filter(event_id=rolled_back_id).exists()
    assert not Branch.all_tenants.filter(name="Failed Branch").exists()


@pytest.mark.django_db
def test_outbox_dispatcher_idempotency() -> None:
    """Prove that the outbox dispatcher executes handlers once and re-runs are idempotent."""
    clear_subscribers()
    org = Organization.objects.create(name="Idempotent Corp", slug="idem-corp")

    invocations: list[str] = []

    @subscribe("idem.action")
    def on_idem_action(evt: OutboxEvent) -> None:
        invocations.append(str(evt.event_id))

    # Publish an event
    evt = publish("idem.action", organization_id=org.id, payload={"data": "test"})

    # Run dispatcher first time
    processed_first = dispatch_outbox_events()
    assert processed_first == 1
    assert len(invocations) == 1
    assert invocations[0] == str(evt.event_id)

    # Verify event transitioned to PROCESSED
    evt.refresh_from_db()
    assert evt.status == OutboxEvent.STATUS_PROCESSED
    assert evt.processed_at is not None

    # Run dispatcher second time: must be idempotent, handler NOT invoked again
    processed_second = dispatch_outbox_events()
    assert processed_second == 0
    assert len(invocations) == 1

    clear_subscribers()


@pytest.mark.django_db
def test_outbox_dispatcher_retry_and_failure() -> None:
    """Verify failed handlers increment retry count and transition to FAILED after max retries."""
    clear_subscribers()
    org = Organization.objects.create(name="Retry Corp", slug="retry-corp")

    attempt_count = 0

    @subscribe("retry.event")
    def on_retry_event(evt: OutboxEvent) -> None:
        nonlocal attempt_count
        attempt_count += 1
        raise ValueError(f"Failing attempt #{attempt_count}")

    evt = publish("retry.event", organization_id=org.id)

    # Attempt 1
    processed = dispatch_outbox_events(max_retries=3)
    assert processed == 0
    evt.refresh_from_db()
    assert evt.status == OutboxEvent.STATUS_PENDING
    assert evt.retry_count == 1
    assert "Failing attempt #1" in evt.last_error

    # Attempt 2
    processed = dispatch_outbox_events(max_retries=3)
    assert processed == 0
    evt.refresh_from_db()
    assert evt.status == OutboxEvent.STATUS_PENDING
    assert evt.retry_count == 2

    # Attempt 3: reaches max_retries=3 -> status transitions to FAILED
    processed = dispatch_outbox_events(max_retries=3)
    assert processed == 0
    evt.refresh_from_db()
    assert evt.status == OutboxEvent.STATUS_FAILED
    assert evt.retry_count == 3

    clear_subscribers()


@pytest.mark.django_db
def test_outbox_dispatcher_executes_in_tenant_context() -> None:
    """Verify that handler execution activates the event's tenant context."""
    clear_subscribers()
    org = Organization.objects.create(name="Context Corp", slug="context-corp")

    captured_org_ids: list[int | None] = []

    @subscribe("tenant.scoped.event")
    def on_scoped_event(evt: OutboxEvent) -> None:
        captured_org_ids.append(get_current_organization_id())

    publish("tenant.scoped.event", organization_id=org.id)
    dispatch_outbox_events()

    assert len(captured_org_ids) == 1
    assert captured_org_ids[0] == org.id

    clear_subscribers()


@pytest.mark.django_db
def test_record_audit_log_service_and_event() -> None:
    """Verify record_audit_log records immutable log and publishes audit.logged event."""
    org = Organization.objects.create(name="Audit Corp", slug="audit-corp")
    actor = User.objects.create_user(email="auditor@test.com", password="PassWord123!")
    branch = Branch.all_tenants.create(organization=org, name="Audit Branch", code="A-BR")

    audit = record_audit_log(
        organization_id=org.id,
        action="branch.created",
        target=branch,
        changes={"name": {"old": None, "new": "Audit Branch"}},
        actor=actor,
        ip_address="192.168.1.100",
        user_agent="TestRunner/1.0",
    )

    assert audit.organization_id == org.id
    assert audit.action == "branch.created"
    assert audit.actor == actor
    assert audit.target_id == str(branch.pk)
    assert audit.ip_address == "192.168.1.100"

    # Verify audit.logged event in outbox
    event = OutboxEvent.objects.filter(event_type="audit.logged", organization=org).first()
    assert event is not None
    assert event.payload["audit_id"] == str(audit.public_id)
    assert event.payload["action"] == "branch.created"


@pytest.mark.django_db
def test_audit_log_tenant_isolation() -> None:
    """Verify that AuditLog respects tenant isolation through TenantManager."""
    org1 = Organization.objects.create(name="Org One", slug="audit-org-1")
    org2 = Organization.objects.create(name="Org Two", slug="audit-org-2")

    record_audit_log(organization_id=org1.id, action="org1.action")
    record_audit_log(organization_id=org2.id, action="org2.action")

    # In org1 context: only org1 audit logs visible
    with tenant_context(org1):
        logs_1 = list(AuditLog.objects.values_list("action", flat=True))
        assert "org1.action" in logs_1
        assert "org2.action" not in logs_1

    # In org2 context: only org2 audit logs visible
    with tenant_context(org2):
        logs_2 = list(AuditLog.objects.values_list("action", flat=True))
        assert "org2.action" in logs_2
        assert "org1.action" not in logs_2
