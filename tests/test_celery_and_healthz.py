"""Tests for Celery TenantTask isolation, queues, beat schedule, and /healthz /readyz probes."""

from __future__ import annotations

import pytest
from celery import shared_task
from django.conf import settings
from django.test import Client

from apps.core.exceptions import TenantAccessError
from apps.core.tasks import TenantTask
from apps.core.tenant_context import get_current_organization_id
from apps.tenancy.models import Branch, Organization


@shared_task(base=TenantTask)
def sample_tenant_background_task(organization_id: int) -> dict[str, object]:
    """Sample tenant task that inspects active context and queries tenant models."""
    active_org_id = get_current_organization_id()
    branches = list(Branch.objects.values_list("name", flat=True))
    return {
        "active_org_id": active_org_id,
        "branches": branches,
    }


@pytest.mark.django_db
def test_tenant_task_enforces_tenant_isolation() -> None:
    """Prove that TenantTask activates tenant context and isolates queries to that organization."""
    org_a = Organization.objects.create(name="Org Task Alpha", slug="org-task-alpha")
    org_b = Organization.objects.create(name="Org Task Beta", slug="org-task-beta")

    Branch.all_tenants.create(organization=org_a, name="Alpha Branch", code="A-BR")
    Branch.all_tenants.create(organization=org_b, name="Beta Branch", code="B-BR")

    # 1. Calling task for Org A
    result_a = sample_tenant_background_task.apply(kwargs={"organization_id": org_a.id}).get()
    assert result_a["active_org_id"] == org_a.id
    assert result_a["branches"] == ["Alpha Branch"]

    # 2. Calling task for Org B
    result_b = sample_tenant_background_task.apply(kwargs={"organization_id": org_b.id}).get()
    assert result_b["active_org_id"] == org_b.id
    assert result_b["branches"] == ["Beta Branch"]

    # 3. Positional argument call
    result_pos = sample_tenant_background_task.apply(args=(org_a.id,)).get()
    assert result_pos["active_org_id"] == org_a.id
    assert result_pos["branches"] == ["Alpha Branch"]

    # 4. Calling task without organization_id raises TenantAccessError
    @shared_task(base=TenantTask)
    def task_missing_tenant() -> None:
        pass

    with pytest.raises(TenantAccessError):
        task_missing_tenant.apply()


def test_celery_queues_and_beat_configuration() -> None:
    """Verify Celery task queues and beat schedule are configured."""
    assert "default" in settings.CELERY_TASK_QUEUES
    assert "high" in settings.CELERY_TASK_QUEUES
    assert "low" in settings.CELERY_TASK_QUEUES

    assert "dispatch-outbox-events" in settings.CELERY_BEAT_SCHEDULE
    schedule_entry = settings.CELERY_BEAT_SCHEDULE["dispatch-outbox-events"]
    assert schedule_entry["task"] == "core.dispatch_outbox_events"


@pytest.mark.django_db
def test_healthz_liveness_probe(client: Client) -> None:
    """Verify /healthz returns 200 OK without requiring an active tenant."""
    resp1 = client.get("/healthz")
    assert resp1.status_code == 200
    assert resp1.json() == {"status": "ok"}

    resp2 = client.get("/healthz/")
    assert resp2.status_code == 200
    assert resp2.json() == {"status": "ok"}


@pytest.mark.django_db
def test_readyz_readiness_probe(client: Client) -> None:
    """Verify /readyz verifies database and cache connectivity."""
    resp1 = client.get("/readyz")
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["status"] == "ready"
    assert data1["checks"]["database"] == "ok"
    assert data1["checks"]["cache"] == "ok"

    resp2 = client.get("/readyz/")
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "ready"
