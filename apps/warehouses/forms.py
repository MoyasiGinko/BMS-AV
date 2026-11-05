"""Forms for warehouse management, branch fulfillment linkages, locations, and supply routes."""

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.inventory.models import LocationType


class WarehouseForm(forms.Form):
    """Form to create or edit warehouse storage facilities."""

    name = forms.CharField(
        label=_("Warehouse Name"),
        max_length=128,
        widget=forms.TextInput(attrs={"class": "form-input"}),
    )
    code = forms.CharField(
        label=_("Warehouse Code"),
        max_length=32,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"}),
    )
    branch_id = forms.IntegerField(
        label=_("Co-located Branch"),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    is_central = forms.BooleanField(
        label=_("Central Distribution Warehouse"),
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
    )
    is_default = forms.BooleanField(
        label=_("Default Warehouse"),
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
    )
    is_active = forms.BooleanField(
        label=_("Is Active"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
    )


class BranchWarehouseForm(forms.Form):
    """Form to map a warehouse to a branch."""

    branch_id = forms.IntegerField(
        label=_("Branch"),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    warehouse_id = forms.IntegerField(
        label=_("Warehouse"),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    is_default = forms.BooleanField(
        label=_("Default for Branch"),
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
    )
    can_sell = forms.BooleanField(
        label=_("Can Sell"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
    )
    can_replenish = forms.BooleanField(
        label=_("Can Replenish"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
    )
    priority = forms.IntegerField(
        label=_("Priority"),
        required=False,
        initial=1,
        min_value=1,
        max_value=99,
        widget=forms.NumberInput(attrs={"class": "form-input"}),
    )


class BranchForm(forms.Form):
    """Form to create or update an operating branch outlet."""

    name = forms.CharField(
        label=_("Branch Name"),
        max_length=128,
        widget=forms.TextInput(attrs={"class": "form-input"}),
    )
    code = forms.CharField(
        label=_("Branch Code"),
        max_length=32,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"}),
    )
    address = forms.CharField(
        label=_("Address"),
        max_length=255,
        required=False,
        widget=forms.Textarea(attrs={"class": "form-textarea", "rows": 2}),
    )
    phone = forms.CharField(
        label=_("Phone"),
        max_length=32,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"}),
    )
    is_headquarters = forms.BooleanField(
        label=_("Headquarters"),
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
    )
    is_active = forms.BooleanField(
        label=_("Is Active"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
    )


class InventoryLocationForm(forms.Form):
    """Form to create or update an InventoryLocation / Bin / Zone."""

    name = forms.CharField(
        label=_("Location Name"),
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": _("e.g. Zone A, Aisle 3, Shelf 2, Bin 10")}),
    )
    code = forms.CharField(
        label=_("Location Code"),
        max_length=64,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": _("e.g. LOC-ZA-01")}),
    )
    location_type = forms.ChoiceField(
        label=_("Location Type"),
        choices=LocationType.choices,
        initial=LocationType.SUB_LOCATION,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    parent_id = forms.IntegerField(
        label=_("Parent Location"),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    warehouse_id = forms.IntegerField(
        label=_("Warehouse"),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    branch_id = forms.IntegerField(
        label=_("Branch"),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    is_stock_holding = forms.BooleanField(
        label=_("Stock Holding"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
    )
    is_active = forms.BooleanField(
        label=_("Is Active"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
    )
    address = forms.CharField(
        label=_("Physical Address"),
        required=False,
        widget=forms.Textarea(attrs={"class": "form-textarea", "rows": 2}),
    )
    notes = forms.CharField(
        label=_("Notes"),
        required=False,
        widget=forms.Textarea(attrs={"class": "form-textarea", "rows": 2}),
    )


class StockSupplyRouteForm(forms.Form):
    """Form to configure dynamic M:N replenishment routes."""

    source_location_id = forms.IntegerField(
        label=_("Source Location / Warehouse"),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    destination_location_id = forms.IntegerField(
        label=_("Destination Location / Outlet"),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    priority = forms.IntegerField(
        label=_("Priority (1 = Highest)"),
        initial=1,
        min_value=1,
        max_value=99,
        widget=forms.NumberInput(attrs={"class": "form-input"}),
    )
    lead_time_days = forms.IntegerField(
        label=_("Lead Time (Days)"),
        initial=0,
        min_value=0,
        widget=forms.NumberInput(attrs={"class": "form-input"}),
    )
    is_preferred = forms.BooleanField(
        label=_("Preferred Route"),
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
    )
    can_auto_replenish = forms.BooleanField(
        label=_("Allow Automated Replenishment"),
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
    )
    notes = forms.CharField(
        label=_("Notes"),
        required=False,
        widget=forms.Textarea(attrs={"class": "form-textarea", "rows": 2}),
    )
