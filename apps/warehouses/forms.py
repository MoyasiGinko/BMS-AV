"""Forms for warehouse management, branch fulfillment linkages, locations, and supply routes."""

from decimal import Decimal
from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.catalog.models import Product, ProductVariant
from apps.inventory.forms import StockTransferForm
from apps.inventory.models import LocationType, StorageType
from apps.tenancy.models import Warehouse, WarehouseType


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
    warehouse_type = forms.ChoiceField(
        label=_("Warehouse Classification"),
        choices=[
            (WarehouseType.PRIMARY, _("Primary Warehouse (Central Hub / Distribution)")),
            (WarehouseType.SECONDARY, _("Secondary Warehouse (Regional / Outlet Storage)")),
        ],
        initial=WarehouseType.PRIMARY,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    branch_id = forms.IntegerField(
        label=_("Operational Branch"),
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

    def clean_warehouse_type(self) -> str:
        return self.cleaned_data.get("warehouse_type") or WarehouseType.PRIMARY


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
    is_storage_synced = forms.BooleanField(
        label=_("Sync Storage Stock"),
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
        help_text=_("When enabled, outlet counts this warehouse storage stock as its own."),
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
    warehouse_name = forms.CharField(
        label=_("Dedicated Warehouse Name"),
        max_length=128,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": _("Auto-generated if empty")}),
    )
    warehouse_code = forms.CharField(
        label=_("Warehouse Code"),
        max_length=32,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": _("Auto-generated if empty")}),
    )
    warehouse_address = forms.CharField(
        label=_("Warehouse Address"),
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": _("Defaults to branch address")}),
    )


class WarehouseTransferPermissionForm(forms.Form):
    """Form to configure transfer authorization between warehouses."""

    source_warehouse_id = forms.IntegerField(
        label=_("Source Warehouse (From)"),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    destination_warehouse_id = forms.IntegerField(
        label=_("Destination Warehouse (To)"),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    can_request = forms.BooleanField(
        label=_("Allow Destination to Request Stock"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
    )
    can_dispatch = forms.BooleanField(
        label=_("Allow Source to Dispatch Stock"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
    )
    priority = forms.IntegerField(
        label=_("Priority (1 = Highest)"),
        initial=1,
        min_value=1,
        max_value=99,
        widget=forms.NumberInput(attrs={"class": "form-input"}),
    )
    notes = forms.CharField(
        label=_("Notes"),
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"}),
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


class WarehouseStorageTypeForm(forms.Form):
    """Form to create or edit dynamic warehouse storage types."""

    warehouse_id = forms.IntegerField(
        label=_("Warehouse"),
        required=False,
        widget=forms.HiddenInput(),
    )
    name = forms.CharField(
        label=_("Storage Name"),
        max_length=128,
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": _("e.g. Cold Storage, Display Floor, Bulk Bay")}),
    )
    code = forms.CharField(
        label=_("Storage Code"),
        max_length=32,
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": _("e.g. COLD-01, DISPLAY")}),
    )
    can_sell = forms.BooleanField(
        label=_("Can Sell Products (Outlets & POS)"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
    )
    is_default_sellable = forms.BooleanField(
        label=_("Default Sales Source"),
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
    )
    description = forms.CharField(
        label=_("Description"),
        required=False,
        widget=forms.Textarea(attrs={"class": "form-textarea", "rows": 2, "placeholder": _("Storage handling notes or restrictions...")}),
    )


class WarehouseStockTransferForm(forms.Form):
    """Form to request or create an inter-warehouse stock transfer with storage zones."""

    source_warehouse_id = forms.IntegerField(
        label=_("Source Warehouse"),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    source_storage_type = forms.CharField(
        label=_("Source Storage"),
        max_length=64,
        initial=StorageType.SELLABLE,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"}),
    )
    destination_warehouse_id = forms.IntegerField(
        label=_("Destination Warehouse"),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    destination_storage_type = forms.CharField(
        label=_("Destination Storage"),
        max_length=64,
        initial=StorageType.SELLABLE,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"}),
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
        label=_("Quantity"),
        max_digits=18,
        decimal_places=4,
        widget=forms.NumberInput(attrs={"class": "form-input", "min": "0.0001", "step": "any"}),
    )
    mode = forms.ChoiceField(
        label=_("Transfer Pipeline Mode"),
        choices=[
            ("request", _("Request Transfer (Requires Sender & Receiver Dual Verification)")),
            ("direct", _("Direct Transfer (Immediate Completion & Auto-Post)")),
        ],
        initial="direct",
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    notes = forms.CharField(
        label=_("Transfer Notes / Reason"),
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-textarea",
                "rows": 2,
                "placeholder": _("Purpose of transfer, handling notes, requisition reference..."),
            }
        ),
    )

    def __init__(self, *args: Any, organization: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        whs = (
            Warehouse.all_tenants.filter(organization=organization, is_active=True)
            .select_related("branch")
            .order_by("name")
        )
        wh_choices = []
        for w in whs:
            if w.branch:
                label = f"🏬 {w.branch.name} — {w.name}"
            elif getattr(w, "is_central", False):
                label = f"🏭 {w.name} ({_('Central Warehouse')})"
            else:
                label = f"📦 {w.name}"
            wh_choices.append((w.pk, label))

        self.fields["source_warehouse_id"].widget.choices = wh_choices
        self.fields["destination_warehouse_id"].widget.choices = wh_choices

        prods = [
            (p.pk, f"{p.name} ({p.sku})")
            for p in Product.all_tenants.filter(organization=organization, is_active=True).order_by("name")
        ]
        self.fields["product_id"].widget.choices = prods

        variants = [("", str(_("No variant / Base product")))] + [
            (v.pk, f"{v.product.name} - {v.name} ({v.sku})")
            for v in ProductVariant.all_tenants.filter(organization=organization, is_active=True)
            .select_related("product")
            .order_by("product__name", "name")
        ]
        self.fields["variant_id"].widget.choices = variants

    def clean_source_storage_type(self) -> str:
        return self.cleaned_data.get("source_storage_type") or StorageType.SELLABLE

    def clean_destination_storage_type(self) -> str:
        return self.cleaned_data.get("destination_storage_type") or StorageType.SELLABLE

    def clean_mode(self) -> str:
        return self.cleaned_data.get("mode") or "direct"


class TransferDispatchForm(forms.Form):
    """Sender verification and dispatch sign-off."""

    carrier = forms.CharField(
        label=_("Carrier / Vehicle / Driver"),
        max_length=128,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": _("e.g. In-house Van, Driver Rahim, Courier...")}),
    )
    tracking_number = forms.CharField(
        label=_("Consignment / Tracking Number"),
        max_length=128,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": _("e.g. TRK-2026-0042...")}),
    )
    dispatch_notes = forms.CharField(
        label=_("Sender Dispatch Remarks"),
        required=False,
        widget=forms.Textarea(attrs={"class": "form-textarea", "rows": 2}),
    )


class TransferReceiveForm(forms.Form):
    """Receiver intake verification and dual sign-off."""

    quantity_received = forms.DecimalField(
        label=_("Quantity Received (Intact)"),
        max_digits=18,
        decimal_places=4,
        widget=forms.NumberInput(attrs={"class": "form-input", "min": "0", "step": "any"}),
    )
    quantity_damaged = forms.DecimalField(
        label=_("Quantity Damaged (In-Transit Loss)"),
        max_digits=18,
        decimal_places=4,
        required=False,
        initial=Decimal("0.0000"),
        widget=forms.NumberInput(attrs={"class": "form-input", "min": "0", "step": "any"}),
    )
    quantity_missing = forms.DecimalField(
        label=_("Quantity Missing (Shortage / Shrinkage)"),
        max_digits=18,
        decimal_places=4,
        required=False,
        initial=Decimal("0.0000"),
        widget=forms.NumberInput(attrs={"class": "form-input", "min": "0", "step": "any"}),
    )
    receive_notes = forms.CharField(
        label=_("Receiver Inspection Remarks"),
        required=False,
        widget=forms.Textarea(attrs={"class": "form-textarea", "rows": 2, "placeholder": _("Verification condition, seal integrity, intake remarks...")}),
    )


class TransferRejectForm(forms.Form):
    """Rejection form with reason."""

    rejection_reason = forms.CharField(
        label=_("Rejection Reason"),
        widget=forms.Textarea(attrs={"class": "form-textarea", "rows": 3, "placeholder": _("Explain why this transfer request cannot be fulfilled...")}),
    )


__all__ = [
    "BranchForm",
    "BranchWarehouseForm",
    "InventoryLocationForm",
    "StockSupplyRouteForm",
    "StockTransferForm",
    "TransferDispatchForm",
    "TransferReceiveForm",
    "TransferRejectForm",
    "WarehouseForm",
    "WarehouseStockTransferForm",
]
