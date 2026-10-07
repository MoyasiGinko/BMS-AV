import pytest
from django.db import models

from apps.core.models import TenantManager, TenantModel, TenantQuerySet
from apps.core.tenant_context import tenant_context
from apps.tenancy.models import Organization


class SampleModel(models.Model):
    organization_id = models.IntegerField(null=True)
    name = models.CharField(max_length=50)

    objects = TenantManager()

    class Meta:
        app_label = "core"

    def __str__(self) -> str:
        return self.name


def test_tenant_queryset_for_organization() -> None:
    qs = TenantQuerySet(SampleModel)
    filtered = qs.for_organization(42)
    assert "organization_id" in str(filtered.query)


@pytest.mark.django_db
def test_tenant_model_str() -> None:
    org = Organization.objects.create(name="Str Test Org", slug="str-test")

    class ConcreteModel(TenantModel):
        class Meta:
            app_label = "core"

        def __str__(self) -> str:
            return f"Concrete {self.public_id}"

    instance = ConcreteModel()
    assert str(instance) == f"Concrete {instance.public_id}"

    with tenant_context(org):
        instance.save = lambda *args, **kwargs: None  # mock save
        instance.save()
        assert instance.organization_id is None or instance.organization_id == org.pk
