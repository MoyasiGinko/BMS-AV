"""Forms for inventory management, stock adjustments, transfers, and cycle counts."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.catalog.models import Product, ProductVariant
from apps.inventory.models import AdjustmentReason
from apps.tenancy.models import Organization, Warehouse


class StockFilterForm(forms.Form):
    """Filter form for stock levels list."""

    warehouse = forms.ChoiceField(
        label=_("Warehouse"),
        required=False,
        widget=forms.Select(attrs={"class": "form-select text-sm py-1.5"}),
    )
    query = forms.CharField(
        label=_("Search"),
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-input text-sm py-1.5",
                "placeholder": _("Search by product name or SKU..."),
            }
        ),
    )
    low_stock_only = forms.BooleanField(
        label=_("Low Stock Only"),
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox rounded"}),
    )

    def __init__(self, *args: Any, organization: Organization, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        whs = Warehouse.objects.filter(organization=organization, is_active=True).order_by("name")
        cast(forms.ChoiceField, self.fields["warehouse"]).choices = [("", _("All Warehouses"))] + [
            (str(w.pk), w.name) for w in whs
        ]


class StockAdjustmentForm(forms.Form):
    """Stock adjustment creation form."""

    warehouse_id = forms.IntegerField(
        label=_("Warehouse"),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    reason = forms.ChoiceField(
        label=_("Adjustment Reason"),
        choices=AdjustmentReason.choices,
        initial=AdjustmentReason.COUNT_VARIANCE,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    product_id = forms.IntegerField(
        label=_("Product"),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    variant_id = forms.IntegerField(
        label=_("Variant"),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    quantity = forms.DecimalField(
        label=_("Quantity Delta (+ to add, - to deduct)"),
        max_digits=18,
        decimal_places=4,
        widget=forms.NumberInput(
            attrs={"class": "form-input", "placeholder": "e.g. 5.0000 or -2.0000", "step": "any"}
        ),
    )
    unit_cost = forms.DecimalField(
        label=_("Unit Cost (Optional for additions)"),
        max_digits=18,
        decimal_places=4,
        required=False,
        initial=Decimal("0.0000"),
        widget=forms.NumberInput(attrs={"class": "form-input", "step": "0.01"}),
    )
    notes = forms.CharField(
        label=_("Notes / Justification"),
        required=False,
        widget=forms.Textarea(
            attrs={"class": "form-textarea", "rows": 3, "placeholder": _("Explain reason for adjustment...")}
        ),
    )

    def __init__(self, *args: Any, organization: Organization, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        whs = Warehouse.objects.filter(organization=organization, is_active=True).order_by("name")
        self.fields["warehouse_id"].widget.choices = [(w.pk, w.name) for w in whs]

        prods = Product.objects.filter(organization=organization, is_active=True).order_by("name")
        self.fields["product_id"].widget.choices = [(p.pk, f"{p.name} ({p.sku})") for p in prods]

        vars_list = ProductVariant.objects.filter(organization=organization, is_active=True).select_related(
            "product"
        )
        self.fields["variant_id"].widget.choices = [("", _("No Variant (Base Product)"))] + [
            (v.pk, f"{v.product.name} - {v.name} ({v.sku})") for v in vars_list
        ]


class StockTransferForm(forms.Form):
    """Stock transfer creation form."""

    source_warehouse_id = forms.IntegerField(
        label=_("Source Warehouse"),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    destination_warehouse_id = forms.IntegerField(
        label=_("Destination Warehouse"),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    product_id = forms.IntegerField(
        label=_("Product"),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    variant_id = forms.IntegerField(
        label=_("Variant"),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    quantity = forms.DecimalField(
        label=_("Transfer Quantity"),
        max_digits=18,
        decimal_places=4,
        widget=forms.NumberInput(attrs={"class": "form-input", "min": "0.0001", "step": "any"}),
    )
    notes = forms.CharField(
        label=_("Transfer Notes"),
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-textarea",
                "rows": 2,
                "placeholder": _("Transfer instructions or vehicle tag..."),
            }
        ),
    )

    def __init__(self, *args: Any, organization: Organization, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        whs = list(Warehouse.objects.filter(organization=organization, is_active=True).order_by("name"))
        wh_choices = [(w.pk, w.name) for w in whs]
        self.fields["source_warehouse_id"].widget.choices = wh_choices
        self.fields["destination_warehouse_id"].widget.choices = wh_choices

        prods = Product.objects.filter(organization=organization, is_active=True).order_by("name")
        self.fields["product_id"].widget.choices = [(p.pk, f"{p.name} ({p.sku})") for p in prods]

        vars_list = ProductVariant.objects.filter(organization=organization, is_active=True).select_related(
            "product"
        )
        self.fields["variant_id"].widget.choices = [("", _("No Variant (Base Product)"))] + [
            (v.pk, f"{v.product.name} - {v.name} ({v.sku})") for v in vars_list
        ]

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        src = cleaned.get("source_warehouse_id")
        dest = cleaned.get("destination_warehouse_id")
        if src and dest and src == dest:
            raise forms.ValidationError(_("Source and destination warehouses cannot be the same."))
        return cleaned


class StockCountForm(forms.Form):
    """Stock cycle count initiation form."""

    warehouse_id = forms.IntegerField(
        label=_("Audit Warehouse"),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    scheduled_date = forms.DateField(
        label=_("Scheduled Audit Date"),
        initial=timezone.now,
        widget=forms.DateInput(attrs={"class": "form-input", "type": "date"}),
    )
    notes = forms.CharField(
        label=_("Audit Instructions / Notes"),
        required=False,
        widget=forms.Textarea(
            attrs={"class": "form-textarea", "rows": 2, "placeholder": _("Audit instructions for team...")}
        ),
    )

    def __init__(self, *args: Any, organization: Organization, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        whs = Warehouse.objects.filter(organization=organization, is_active=True).order_by("name")
        self.fields["warehouse_id"].widget.choices = [(w.pk, w.name) for w in whs]
