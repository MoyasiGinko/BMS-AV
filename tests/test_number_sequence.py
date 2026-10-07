import datetime

import pytest

from apps.core.models import NumberSequence
from apps.core.selectors import get_number_sequence, list_number_sequences
from apps.core.services import generate_next_number
from apps.core.tenant_context import tenant_context
from apps.tenancy.models import Organization


@pytest.mark.django_db
def test_generate_next_number_default() -> None:
    org = Organization.objects.create(name="Sequence Org", slug="seq-org")
    num1 = generate_next_number(
        organization_id=org.pk,
        name="invoice",
        prefix="INV-",
        padding=4,
    )
    assert num1 == "INV-0001"

    num2 = generate_next_number(
        organization_id=org.pk,
        name="invoice",
    )
    assert num2 == "INV-0002"


@pytest.mark.django_db
def test_generate_next_number_isolation() -> None:
    org1 = Organization.objects.create(name="Org One", slug="org1")
    org2 = Organization.objects.create(name="Org Two", slug="org2")

    n1 = generate_next_number(organization_id=org1.pk, name="order", prefix="ORD-")
    n2 = generate_next_number(organization_id=org2.pk, name="order", prefix="ORD-")

    assert n1 == "ORD-00001"
    assert n2 == "ORD-00001"


@pytest.mark.django_db
def test_generate_next_number_yearly_reset() -> None:
    org = Organization.objects.create(name="Yearly Org", slug="yearly-org")
    d1 = datetime.date(2025, 12, 31)
    d2 = datetime.date(2026, 1, 1)

    n1 = generate_next_number(
        organization_id=org.pk,
        name="receipt",
        prefix="REC-",
        reset_frequency=NumberSequence.RESET_YEARLY,
        current_date=d1,
    )
    assert n1 == "REC-00001"

    n2 = generate_next_number(
        organization_id=org.pk,
        name="receipt",
        prefix="REC-",
        reset_frequency=NumberSequence.RESET_YEARLY,
        current_date=d1,
    )
    assert n2 == "REC-00002"

    # Next year -> resets to 00001
    n3 = generate_next_number(
        organization_id=org.pk,
        name="receipt",
        prefix="REC-",
        reset_frequency=NumberSequence.RESET_YEARLY,
        current_date=d2,
    )
    assert n3 == "REC-00001"


@pytest.mark.django_db
def test_generate_next_number_monthly_reset() -> None:
    org = Organization.objects.create(name="Monthly Org", slug="monthly-org")
    d1 = datetime.date(2026, 1, 31)
    d2 = datetime.date(2026, 2, 1)

    n1 = generate_next_number(
        organization_id=org.pk,
        name="ticket",
        prefix="TCK-",
        reset_frequency=NumberSequence.RESET_MONTHLY,
        current_date=d1,
    )
    assert n1 == "TCK-00001"

    # Next month -> resets
    n2 = generate_next_number(
        organization_id=org.pk,
        name="ticket",
        prefix="TCK-",
        reset_frequency=NumberSequence.RESET_MONTHLY,
        current_date=d2,
    )
    assert n2 == "TCK-00001"


@pytest.mark.django_db
def test_number_sequence_tenant_scoped_query() -> None:
    org1 = Organization.objects.create(name="Scoped Org 1", slug="scoped1")
    org2 = Organization.objects.create(name="Scoped Org 2", slug="scoped2")

    generate_next_number(organization_id=org1.pk, name="seq1")
    generate_next_number(organization_id=org2.pk, name="seq2")

    with tenant_context(org1):
        assert NumberSequence.objects.count() == 1
        assert NumberSequence.objects.first().name == "seq1"  # type: ignore[union-attr]

    with tenant_context(org2):
        assert NumberSequence.objects.count() == 1
        assert NumberSequence.objects.first().name == "seq2"  # type: ignore[union-attr]

    # Outside tenant context -> none returned by scoped objects
    assert NumberSequence.objects.count() == 0
    # unscoped manager sees all
    assert NumberSequence.all_tenants.count() == 2


@pytest.mark.django_db
def test_number_sequence_selectors() -> None:
    org = Organization.objects.create(name="Selector Org", slug="sel-org")
    generate_next_number(organization_id=org.pk, name="inv", prefix="INV-")
    generate_next_number(organization_id=org.pk, name="quote", prefix="QTE-")

    seq = get_number_sequence(organization_id=org.pk, name="inv")
    assert seq is not None
    assert seq.prefix == "INV-"
    assert str(seq) == "inv (INV-...)"

    assert get_number_sequence(organization_id=org.pk, name="nonexistent") is None

    seqs = list_number_sequences(organization_id=org.pk)
    assert seqs.count() == 2
    assert list(seqs.values_list("name", flat=True)) == ["inv", "quote"]
