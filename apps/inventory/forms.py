"""Forms for inventory management, stock adjustments, transfers, and cycle counts."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.catalog.models import Product, ProductVariant
from apps.inventory.models import AdjustmentReason
from apps.tenancy.models import Branch, Organization, Warehouse


class StockFilterForm(forms.Form):
    """Filter form for stock levels list."""

    warehouse = forms.ChoiceField(
        label=_("Warehouse"),
        required=False,
        widget=forms.Select(
            attrs={
                "class": "neu-select form-select text-sm rounded-xl px-3.5 py-2.5 font-medium cursor-pointer w-full"
            }
        ),
    )
    query = forms.CharField(
        label=_("Search"),
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "neu-input form-input text-sm rounded-xl px-4 py-2.5 font-medium w-full",
                "placeholder": _("Search by product name or SKU..."),
            }
        ),
    )
    low_stock_only = forms.BooleanField(
        label=_("Low Stock Only"),
        required=False,
        widget=forms.CheckboxInput(
            attrs={
                "class": "form-checkbox rounded text-indigo-600 focus:ring-indigo-500 w-4 h-4 cursor-pointer"
            }
        ),
    )

    def __init__(self, *args: Any, organization: Organization, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        whs = (
            Warehouse.objects.filter(organization=organization, is_active=True)
            .select_related("branch", "dedicated_assignment__branch")
            .prefetch_related("warehouse_branches__branch")
            .order_by("name")
        )
        primary_choices: list[tuple[str, str]] = []
        dedicated_choices: list[tuple[str, str]] = []
        synced_wh_choices: list[tuple[str, str]] = []
        synced_branch_choices: list[tuple[str, str]] = []

        for w in whs:
            sync_branches = list(w.warehouse_branches.filter(relationship_type="synchronized").select_related("branch"))
            if sync_branches:
                b_names = ", ".join(bw.branch.name for bw in sync_branches)
                synced_wh_choices.append((str(w.pk), f"🔄 {w.name} (Combined Total: {b_names})"))
                for bw in sync_branches:
                    synced_branch_choices.append((f"branch:{bw.branch.pk}", f"📍 {bw.branch.name} (Synced to {w.name})"))
            elif getattr(w, "is_primary", False) or getattr(w, "is_central", False):
                primary_choices.append((str(w.pk), f"🏢 {w.name} (Primary Central Hub)"))
            else:
                br = getattr(w, "dedicated_branch", None) or w.branch
                br_name = f" • {br.name}" if br else ""
                dedicated_choices.append((str(w.pk), f"🏬 {w.name} (Dedicated{br_name})"))

        choices: list[Any] = [("", _("All Facilities (Combined Synced Pools)"))]
        if primary_choices:
            choices.append((_("Primary Central Hubs"), primary_choices))
        if dedicated_choices:
            choices.append((_("Branch Dedicated Warehouses"), dedicated_choices))
        if synced_wh_choices:
            choices.append((_("Synchronized Warehouses (Combined Pools)"), synced_wh_choices))
        if synced_branch_choices:
            choices.append((_("Individual Synced Outlets"), synced_branch_choices))
        if len(choices) == 1:
            choices.extend([(str(w.pk), w.name) for w in whs])
        cast(forms.ChoiceField, self.fields["warehouse"]).choices = choices


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


class StockRequestForm(forms.Form):
    """Form to initiate a branch stock replenishment request from a linked warehouse."""

    branch_id = forms.IntegerField(
        label=_("Requesting Branch / Outlet"),
        widget=forms.Select(attrs={"class": "neu-select form-select w-full text-sm rounded-xl px-3.5 py-2.5 font-medium"}),
    )
    warehouse_id = forms.IntegerField(
        label=_("Fulfillment Source Warehouse"),
        widget=forms.Select(attrs={"class": "neu-select form-select w-full text-sm rounded-xl px-3.5 py-2.5 font-medium"}),
    )
    notes = forms.CharField(
        label=_("Request Notes / Delivery Instructions"),
        required=False,
        widget=forms.Textarea(
            attrs={"class": "neu-input form-textarea w-full text-sm rounded-xl p-3 font-medium", "rows": 2, "placeholder": _("Delivery deadline, urgency, or notes...")}
        ),
    )

    def __init__(self, *args: Any, organization: Organization, branch_id: int | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        branches = Branch.objects.filter(organization=organization, is_active=True).order_by("name")
        self.fields["branch_id"].widget.choices = [(b.pk, b.name) for b in branches]
        if branch_id:
            self.fields["branch_id"].initial = branch_id

        whs = Warehouse.objects.filter(organization=organization, is_active=True).order_by("name")
        self.fields["warehouse_id"].widget.choices = [(w.pk, w.name) for w in whs]
