"""Forms for catalog management and CSV import."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.catalog.models import (
    Category,
    Product,
    ProductType,
    Unit,
)
from apps.tenancy.models import TaxCode


class ProductForm(forms.Form):
    """Product create and update form."""

    sku = forms.CharField(
        label=_("SKU"),
        max_length=64,
        widget=forms.TextInput(attrs={"class": "w-full px-4 py-3.5 text-base font-medium rounded-xl border border-line bg-surface text-ink placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-2xs transition-all", "placeholder": "e.g. PROD-001"}),
    )
    name = forms.CharField(
        label=_("Product Name"),
        max_length=255,
        widget=forms.TextInput(attrs={"class": "w-full px-4 py-3.5 text-base font-medium rounded-xl border border-line bg-surface text-ink placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-2xs transition-all", "placeholder": "e.g. Wireless Ergonomic Mouse"}),
    )
    barcode = forms.CharField(
        label=_("Barcode / UPC / EAN"),
        max_length=64,
        required=False,
        widget=forms.TextInput(attrs={"class": "w-full px-4 py-3.5 text-base font-medium rounded-xl border border-line bg-surface text-ink placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-2xs transition-all", "placeholder": "e.g. 012345678905"}),
    )
    category_id = forms.IntegerField(
        label=_("Category"),
        required=False,
        widget=forms.Select(attrs={"class": "w-full px-4 py-3.5 text-base font-medium rounded-xl border border-line bg-surface text-ink focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-2xs transition-all cursor-pointer"}),
    )
    unit_id = forms.IntegerField(
        label=_("Unit of Measure"),
        widget=forms.Select(attrs={"class": "w-full px-4 py-3.5 text-base font-medium rounded-xl border border-line bg-surface text-ink focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-2xs transition-all cursor-pointer"}),
    )
    type = forms.ChoiceField(
        label=_("Product Type"),
        choices=ProductType.choices,
        initial=ProductType.STOCK,
        widget=forms.Select(attrs={"class": "w-full px-4 py-3.5 text-base font-medium rounded-xl border border-line bg-surface text-ink focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-2xs transition-all cursor-pointer"}),
    )
    cost_price = forms.DecimalField(
        label=_("Cost Price"),
        max_digits=18,
        decimal_places=4,
        initial=Decimal("0.0000"),
        widget=forms.NumberInput(attrs={"class": "w-full px-4 py-3.5 text-base font-medium rounded-xl border border-line bg-surface text-ink placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-2xs transition-all", "step": "0.01"}),
    )
    selling_price = forms.DecimalField(
        label=_("Selling Price"),
        max_digits=18,
        decimal_places=4,
        initial=Decimal("0.0000"),
        widget=forms.NumberInput(attrs={"class": "w-full px-4 py-3.5 text-base font-medium rounded-xl border border-line bg-surface text-ink placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-2xs transition-all", "step": "0.01"}),
    )
    discount_percent = forms.DecimalField(
        label=_("Discount (%)"),
        max_digits=5,
        decimal_places=2,
        required=False,
        initial=Decimal("0.00"),
        widget=forms.NumberInput(attrs={"class": "w-full px-4 py-3.5 text-base font-medium rounded-xl border border-line bg-surface text-ink placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-2xs transition-all", "step": "0.5", "min": "0", "max": "100", "placeholder": "0.00"}),
    )
    tax_code_id = forms.IntegerField(
        label=_("Tax Code"),
        required=False,
        widget=forms.Select(attrs={"class": "w-full px-4 py-3.5 text-base font-medium rounded-xl border border-line bg-surface text-ink focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-2xs transition-all cursor-pointer"}),
    )
    reorder_level = forms.DecimalField(
        label=_("Reorder Level"),
        max_digits=18,
        decimal_places=4,
        required=False,
        initial=Decimal("0.0000"),
        widget=forms.NumberInput(attrs={"class": "w-full px-4 py-3.5 text-base font-medium rounded-xl border border-line bg-surface text-ink placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-2xs transition-all", "step": "1"}),
    )
    reorder_quantity = forms.DecimalField(
        label=_("Reorder Quantity"),
        max_digits=18,
        decimal_places=4,
        required=False,
        initial=Decimal("0.0000"),
        widget=forms.NumberInput(attrs={"class": "w-full px-4 py-3.5 text-base font-medium rounded-xl border border-line bg-surface text-ink placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-2xs transition-all", "step": "1"}),
    )
    is_active = forms.BooleanField(
        label=_("Active in catalog"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "w-5 h-5 rounded-md border-line text-indigo-600 focus:ring-indigo-500 bg-surface transition-all cursor-pointer"}),
    )
    track_batch = forms.BooleanField(
        label=_("Track lot / batches"),
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={"class": "w-5 h-5 rounded-md border-line text-indigo-600 focus:ring-indigo-500 bg-surface transition-all cursor-pointer"}),
    )
    track_serial = forms.BooleanField(
        label=_("Track unique serial numbers"),
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={"class": "w-5 h-5 rounded-md border-line text-indigo-600 focus:ring-indigo-500 bg-surface transition-all cursor-pointer"}),
    )
    description = forms.CharField(
        label=_("Description"),
        required=False,
        widget=forms.Textarea(attrs={"class": "w-full px-4 py-3.5 text-base font-medium rounded-xl border border-line bg-surface text-ink placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-2xs transition-all resize-y", "rows": 4, "placeholder": "Provide detailed specifications, features, or operational handling instructions..."}),
    )

    def __init__(self, *args: Any, organization_id: int | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if organization_id:
            cats = [("", _("-- Select Category (Optional) --"))] + [
                (c.pk, str(c))
                for c in Category.all_tenants.filter(organization_id=organization_id, is_active=True)
            ]
            self.fields["category_id"].widget.choices = cats

            units = [
                (u.pk, str(u))
                for u in Unit.all_tenants.filter(organization_id=organization_id, is_active=True)
            ]
            self.fields["unit_id"].widget.choices = units

            tax_codes = [("", _("-- No Tax / Standard --"))] + [
                (t.pk, str(t))
                for t in TaxCode.all_tenants.filter(organization_id=organization_id, is_active=True)
            ]
            self.fields["tax_code_id"].widget.choices = tax_codes


class ProductVariantForm(forms.Form):
    """Product variant creation form."""

    sku = forms.CharField(
        label=_("Variant SKU"),
        max_length=64,
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": "e.g. PROD-001-RED"}),
    )
    name = forms.CharField(
        label=_("Variant Name / Description"),
        max_length=128,
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": "e.g. Red, Large"}),
    )
    barcode = forms.CharField(
        label=_("Barcode"),
        max_length=64,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"}),
    )
    cost_price_override = forms.DecimalField(
        label=_("Cost Price Override"),
        max_digits=18,
        decimal_places=4,
        required=False,
        widget=forms.NumberInput(attrs={"class": "w-full px-4 py-3.5 text-base font-medium rounded-xl border border-line bg-surface text-ink placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-2xs transition-all", "step": "0.01"}),
    )
    selling_price_override = forms.DecimalField(
        label=_("Selling Price Override"),
        max_digits=18,
        decimal_places=4,
        required=False,
        widget=forms.NumberInput(attrs={"class": "w-full px-4 py-3.5 text-base font-medium rounded-xl border border-line bg-surface text-ink placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-2xs transition-all", "step": "0.01"}),
    )
    is_active = forms.BooleanField(
        label=_("Active"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "w-5 h-5 rounded-md border-line text-indigo-600 focus:ring-indigo-500 bg-surface transition-all cursor-pointer"}),
    )


class CategoryForm(forms.Form):
    """Category form."""

    name = forms.CharField(
        label=_("Category Name"),
        max_length=128,
        widget=forms.TextInput(attrs={"class": "form-input"}),
    )
    slug = forms.CharField(
        label=_("Slug (Auto-generated if empty)"),
        max_length=128,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"}),
    )
    parent_id = forms.IntegerField(
        label=_("Parent Category"),
        required=False,
        widget=forms.Select(attrs={"class": "w-full px-4 py-3.5 text-base font-medium rounded-xl border border-line bg-surface text-ink focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-2xs transition-all cursor-pointer"}),
    )
    description = forms.CharField(
        label=_("Description"),
        required=False,
        widget=forms.Textarea(attrs={"class": "form-input", "rows": 2}),
    )
    is_active = forms.BooleanField(
        label=_("Active"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "w-5 h-5 rounded-md border-line text-indigo-600 focus:ring-indigo-500 bg-surface transition-all cursor-pointer"}),
    )

    def __init__(self, *args: Any, organization_id: int | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if organization_id:
            cats = [("", _("-- Top Level (No Parent) --"))] + [
                (c.pk, str(c))
                for c in Category.all_tenants.filter(organization_id=organization_id, is_active=True)
            ]
            self.fields["parent_id"].widget.choices = cats


class UnitForm(forms.Form):
    """Unit of measure form."""

    name = forms.CharField(
        label=_("Unit Name"),
        max_length=64,
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": "e.g. Kilogram"}),
    )
    code = forms.CharField(
        label=_("Short Code"),
        max_length=16,
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": "e.g. kg"}),
    )
    precision = forms.IntegerField(
        label=_("Decimal Places"),
        initial=0,
        min_value=0,
        max_value=4,
        widget=forms.NumberInput(attrs={"class": "form-input"}),
    )


class PriceListForm(forms.Form):
    """Price list form."""

    name = forms.CharField(
        label=_("Price List Name"),
        max_length=128,
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": "e.g. Wholesale Tier A"}),
    )
    currency = forms.CharField(
        label=_("Currency"),
        max_length=3,
        initial="USD",
        widget=forms.TextInput(attrs={"class": "form-input"}),
    )
    is_default = forms.BooleanField(
        label=_("Default Price List"),
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "w-5 h-5 rounded-md border-line text-indigo-600 focus:ring-indigo-500 bg-surface transition-all cursor-pointer"}),
    )
    description = forms.CharField(
        label=_("Description"),
        required=False,
        widget=forms.Textarea(attrs={"class": "form-input", "rows": 2}),
    )


class PriceListItemForm(forms.Form):
    """Price list item override form."""

    product_id = forms.IntegerField(
        label=_("Product"),
        widget=forms.Select(attrs={"class": "w-full px-4 py-3.5 text-base font-medium rounded-xl border border-line bg-surface text-ink focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-2xs transition-all cursor-pointer"}),
    )
    price = forms.DecimalField(
        label=_("Special Price"),
        max_digits=18,
        decimal_places=4,
        widget=forms.NumberInput(attrs={"class": "w-full px-4 py-3.5 text-base font-medium rounded-xl border border-line bg-surface text-ink placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-2xs transition-all", "step": "0.01"}),
    )
    min_quantity = forms.DecimalField(
        label=_("Minimum Quantity"),
        max_digits=18,
        decimal_places=4,
        initial=Decimal("1.0000"),
        widget=forms.NumberInput(attrs={"class": "w-full px-4 py-3.5 text-base font-medium rounded-xl border border-line bg-surface text-ink placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-2xs transition-all", "step": "1"}),
    )

    def __init__(self, *args: Any, organization_id: int | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if organization_id:
            prods = [
                (p.pk, f"{p.name} ({p.sku})")
                for p in Product.all_tenants.filter(organization_id=organization_id, is_active=True)
            ]
            self.fields["product_id"].widget.choices = prods


class CsvImportForm(forms.Form):
    """CSV file upload form."""

    csv_file = forms.FileField(
        label=_("CSV File"),
        widget=forms.FileInput(attrs={"class": "form-input", "accept": ".csv"}),
    )
    update_existing = forms.BooleanField(
        label=_("Update existing products matching SKU"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "w-5 h-5 rounded-md border-line text-indigo-600 focus:ring-indigo-500 bg-surface transition-all cursor-pointer"}),
    )
