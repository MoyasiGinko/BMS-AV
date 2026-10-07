import pytest

from apps.tenancy.models import Organization


@pytest.mark.django_db
def test_create_organization() -> None:
    org = Organization.objects.create(name="Acme Corp", slug="acme")
    assert org.name == "Acme Corp"
    assert org.slug == "acme"
    assert str(org) == "Acme Corp"
    assert org.is_active
    assert org.base_currency == "USD"
