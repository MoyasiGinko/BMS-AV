import pytest

from apps.core.exceptions import TenantAccessError
from apps.core.tenant_context import (
    get_current_organization,
    get_current_organization_id,
    require_current_organization,
    require_current_organization_id,
    set_current_organization,
    tenant_context,
)
from apps.tenancy.models import Organization


@pytest.mark.django_db
def test_tenant_context_manager() -> None:
    org = Organization.objects.create(name="Tenant One", slug="t1")
    assert get_current_organization() is None
    assert get_current_organization_id() is None

    with tenant_context(org):
        assert get_current_organization() == org
        assert get_current_organization_id() == org.pk

    assert get_current_organization() is None
    assert get_current_organization_id() is None


@pytest.mark.django_db
def test_set_current_organization() -> None:
    org = Organization.objects.create(name="Tenant Two", slug="t2")
    set_current_organization(org)
    assert get_current_organization() == org
    assert get_current_organization_id() == org.pk
    set_current_organization(None)
    assert get_current_organization() is None
    assert get_current_organization_id() is None


@pytest.mark.django_db
def test_require_current_organization() -> None:
    with pytest.raises(TenantAccessError):
        require_current_organization()

    with pytest.raises(TenantAccessError):
        require_current_organization_id()

    org = Organization.objects.create(name="Required Org", slug="req-org")
    with tenant_context(org):
        assert require_current_organization() == org
        assert require_current_organization_id() == org.pk
