"""Tests for Number Sequence Statutory Void Engine and Register Sequence Blocks.

Enforces AGENTS.md Section 8 & Section 15 Task 8:
- Receipt and invoice numbers for offline registers come from pre-allocated blocks per register.
- Gaps are recorded as void, never silently skipped (statutory serials unbroken).
- Statutory void document number recording and retrieval.
- Tenant isolation across number sequences, void records, and register blocks.
"""

from __future__ import annotations

import pytest

from apps.core.models import NumberSequence, VoidDocumentNumber
from apps.core.services import (
    detect_and_record_sequence_gaps,
    list_void_document_numbers,
    record_void_document_number,
)
from apps.core.tenant_context import tenant_context
from apps.pos.exceptions import SequenceBlockExhaustedError
from apps.pos.models import POSRegister
from apps.pos.services import (
    allocate_register_sequence_block,
    consume_next_number_from_block,
    record_register_block_gaps,
)
from apps.tenancy.models import Branch, Organization, Warehouse


@pytest.fixture
def test_org() -> Organization:
    return Organization.objects.create(name="Bengal Retail Ltd", slug="bengal-retail")


@pytest.fixture
def other_org() -> Organization:
    return Organization.objects.create(name="Padma Traders", slug="padma-traders")


@pytest.fixture
def test_register(test_org: Organization) -> POSRegister:
    branch = Branch.objects.create(organization=test_org, name="Dhanmondi Branch", code="DHN-01")
    warehouse = Warehouse.objects.create(
        organization=test_org, branch=branch, name="Dhanmondi Storage", code="WH-DHN-01"
    )
    return POSRegister.objects.create(
        organization=test_org,
        branch=branch,
        warehouse=warehouse,
        name="Front Counter Register 1",
        code="REG-01",
    )


@pytest.mark.django_db
class TestNumberSequenceVoidEngine:
    def test_record_and_list_void_document_number(self, test_org: Organization) -> None:
        """Void document numbers are recorded with reason, sequence, and source."""
        seq = NumberSequence.all_tenants.create(
            organization=test_org,
            name="sales_invoice",
            prefix="INV-",
            padding=5,
            next_number=10,
        )

        void_doc = record_void_document_number(
            organization_id=test_org.pk,
            sequence=seq,
            document_number="INV-00007",
            sequence_number=7,
            reason="Printer jam during thermal print",
            source="Terminal A",
        )

        assert void_doc.document_number == "INV-00007"
        assert void_doc.sequence_number == 7
        assert void_doc.reason == "Printer jam during thermal print"
        assert void_doc.source == "Terminal A"

        # Query void list
        voids = list(list_void_document_numbers(organization_id=test_org.pk, sequence_name="sales_invoice"))
        assert len(voids) == 1
        assert voids[0].pk == void_doc.pk

    def test_detect_and_record_sequence_gaps(self, test_org: Organization) -> None:
        """Gaps between expected and actual sequential numbers are recorded as voids."""
        seq = NumberSequence.all_tenants.create(
            organization=test_org,
            name="tax_invoice",
            prefix="TAX-",
            padding=4,
            next_number=1,
        )

        # Expected was 5, but jump to 8 occurred (numbers 5, 6, 7 were skipped)
        gaps = detect_and_record_sequence_gaps(
            organization_id=test_org.pk,
            sequence=seq,
            expected_next=5,
            actual_next=8,
            reason="Hardware communication drop",
        )

        assert len(gaps) == 3
        doc_numbers = [g.document_number for g in gaps]
        assert doc_numbers == ["TAX-0005", "TAX-0006", "TAX-0007"]
        seq_nums = [g.sequence_number for g in gaps]
        assert seq_nums == [5, 6, 7]

    def test_allocate_register_sequence_block(
        self, test_org: Organization, test_register: POSRegister
    ) -> None:
        """Registers can be pre-allocated sequence blocks for offline operations."""
        block = allocate_register_sequence_block(
            organization=test_org,
            register=test_register,
            sequence_name="pos_receipt",
            block_size=50,
        )

        assert block.organization == test_org
        assert block.register == test_register
        assert block.range_start == 1
        assert block.range_end == 50
        assert block.next_number == 1
        assert block.is_active is True

        # Second block allocation continues unbroken from the previous block end
        second_block = allocate_register_sequence_block(
            organization=test_org,
            register=test_register,
            sequence_name="pos_receipt",
            block_size=50,
        )
        assert second_block.range_start == 51
        assert second_block.range_end == 100
        assert second_block.next_number == 51

    def test_consume_numbers_from_block_until_exhaustion(
        self, test_org: Organization, test_register: POSRegister
    ) -> None:
        """Numbers are consumed sequentially from the block; exhausting the block raises an error."""
        block = allocate_register_sequence_block(
            organization=test_org,
            register=test_register,
            sequence_name="pos_receipt",
            block_size=3,
        )

        num1, fmt1 = consume_next_number_from_block(block=block)
        assert num1 == 1
        assert fmt1 == "REC-REG-01-00001"

        num2, fmt2 = consume_next_number_from_block(block=block)
        assert num2 == 2
        assert fmt2 == "REC-REG-01-00002"

        num3, fmt3 = consume_next_number_from_block(block=block)
        assert num3 == 3
        assert fmt3 == "REC-REG-01-00003"

        # Block is now exhausted; subsequent consumption fails
        with pytest.raises(SequenceBlockExhaustedError):
            consume_next_number_from_block(block=block)

    def test_record_register_block_gaps(
        self, test_org: Organization, test_register: POSRegister
    ) -> None:
        """Gaps in numbers returned from offline sync are marked as statutory voids."""
        block = allocate_register_sequence_block(
            organization=test_org,
            register=test_register,
            sequence_name="pos_receipt",
            block_size=10,
        )

        # Offline register only submitted receipts 1, 2, 4 (receipt 3 was skipped/cancelled)
        used = {1, 2, 4}
        voids = record_register_block_gaps(block=block, used_numbers=used, reason="Offline sync void")

        assert len(voids) == 1
        assert voids[0].document_number == "REC-REG-01-00003"
        assert voids[0].sequence_number == 3
        assert voids[0].reason == "Offline sync void"

    def test_void_records_tenant_isolation(
        self, test_org: Organization, other_org: Organization
    ) -> None:
        """Void document numbers of tenant A cannot be seen or queried by tenant B."""
        seq_a = NumberSequence.all_tenants.create(
            organization=test_org, name="seq", prefix="A-", padding=3, next_number=1
        )
        seq_b = NumberSequence.all_tenants.create(
            organization=other_org, name="seq", prefix="B-", padding=3, next_number=1
        )

        void_a = record_void_document_number(
            organization_id=test_org.pk,
            sequence=seq_a,
            document_number="A-001",
            reason="Void in tenant A",
        )
        void_b = record_void_document_number(
            organization_id=other_org.pk,
            sequence=seq_b,
            document_number="B-001",
            reason="Void in tenant B",
        )

        list_a = list_void_document_numbers(organization_id=test_org.pk)
        assert void_a in list_a
        assert void_b not in list_a

        with tenant_context(test_org):
            assert VoidDocumentNumber.objects.filter(pk=void_a.pk).exists()
            assert not VoidDocumentNumber.objects.filter(pk=void_b.pk).exists()
