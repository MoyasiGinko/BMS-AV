"""DRF Serializers for customer entities, subledger, and statements."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from rest_framework import serializers

from apps.customers import services
from apps.customers.models import (
    Customer,
    CustomerAddress,
    CustomerBalanceEntry,
    CustomerContact,
)


class CustomerAddressSerializer(serializers.ModelSerializer[CustomerAddress]):
    """Serializer for customer address objects."""

    public_id = serializers.UUIDField(read_only=True)
    customer = serializers.SlugRelatedField(slug_field="public_id", queryset=Customer.all_tenants.all())

    class Meta:
        model = CustomerAddress
        fields = [
            "public_id",
            "customer",
            "type",
            "recipient_name",
            "line1",
            "line2",
            "city",
            "state_or_province",
            "postal_code",
            "country",
            "phone",
            "is_default",
            "created_at",
            "updated_at",
        ]


class CustomerContactSerializer(serializers.ModelSerializer[CustomerContact]):
    """Serializer for individual customer contacts."""

    public_id = serializers.UUIDField(read_only=True)
    customer = serializers.SlugRelatedField(slug_field="public_id", queryset=Customer.all_tenants.all())
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = CustomerContact
        fields = [
            "public_id",
            "customer",
            "first_name",
            "last_name",
            "full_name",
            "title",
            "email",
            "phone",
            "is_primary",
            "notes",
            "created_at",
            "updated_at",
        ]


class CustomerBalanceEntrySerializer(serializers.ModelSerializer[CustomerBalanceEntry]):
    """Serializer for immutable customer subledger entries."""

    public_id = serializers.UUIDField(read_only=True)
    customer_code = serializers.CharField(source="customer.code", read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)

    class Meta:
        model = CustomerBalanceEntry
        fields = [
            "public_id",
            "customer_code",
            "customer_name",
            "entry_type",
            "debit",
            "credit",
            "balance_after",
            "reference_type",
            "reference_id",
            "reference_number",
            "description",
            "occurred_at",
            "created_at",
        ]
        read_only_fields = fields


class CustomerSerializer(serializers.ModelSerializer[Customer]):
    """Serializer for customer list and lightweight resource representation."""

    public_id = serializers.UUIDField(read_only=True)
    available_credit = serializers.DecimalField(max_digits=18, decimal_places=4, read_only=True)
    is_credit_exceeded = serializers.BooleanField(read_only=True)
    price_list_name = serializers.CharField(source="price_list.name", read_only=True, allow_null=True)

    class Meta:
        model = Customer
        fields = [
            "public_id",
            "code",
            "name",
            "type",
            "status",
            "email",
            "phone",
            "tax_id",
            "currency",
            "price_list",
            "price_list_name",
            "credit_limit",
            "payment_terms_days",
            "current_balance",
            "total_spent",
            "available_credit",
            "is_credit_exceeded",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "public_id",
            "current_balance",
            "total_spent",
            "available_credit",
            "is_credit_exceeded",
            "created_at",
            "updated_at",
        ]


class CustomerDetailSerializer(CustomerSerializer):
    """Detailed customer serializer including nested addresses and contacts."""

    addresses = CustomerAddressSerializer(many=True, read_only=True)
    contacts = CustomerContactSerializer(many=True, read_only=True)

    class Meta(CustomerSerializer.Meta):
        fields = [*CustomerSerializer.Meta.fields, "addresses", "contacts"]


class CustomerCreateSerializer(serializers.ModelSerializer[Customer]):
    """Serializer for creating customer accounts."""

    code = serializers.CharField(required=False, allow_blank=True)
    current_balance = serializers.DecimalField(max_digits=18, decimal_places=4, read_only=True)
    opening_balance = serializers.DecimalField(
        max_digits=18,
        decimal_places=4,
        required=False,
        default=Decimal("0.0000"),
        write_only=True,
    )

    class Meta:
        model = Customer
        fields = [
            "public_id",
            "code",
            "name",
            "type",
            "status",
            "email",
            "phone",
            "tax_id",
            "currency",
            "price_list",
            "credit_limit",
            "payment_terms_days",
            "current_balance",
            "opening_balance",
            "notes",
        ]
        read_only_fields = ["public_id", "current_balance"]

    def create(self, validated_data: dict[str, Any]) -> Customer:
        request = self.context.get("request")
        org = validated_data.pop("organization", getattr(request, "organization", None))
        actor = validated_data.pop("created_by", getattr(request, "user", None))
        opening_bal = validated_data.pop("opening_balance", Decimal("0.0000"))
        return services.create_customer(
            organization=org,
            actor=actor,
            opening_balance=opening_bal,
            **validated_data,
        )


class CustomerAdjustmentInputSerializer(serializers.Serializer):
    """Input serializer for posting manual subledger adjustments."""

    adjustment_type = serializers.ChoiceField(choices=["debit", "credit"])
    amount = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))
    reason = serializers.CharField(max_length=500)
    reference_number = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
