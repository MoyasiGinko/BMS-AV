"""Models for product catalog, categories, units, variants, and pricing."""

from __future__ import annotations

from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantModel


class Category(TenantModel):
    """Hierarchical product category tree."""

    name = models.CharField(_("category name"), max_length=128)
    slug = models.SlugField(_("slug"), max_length=128)
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
        verbose_name=_("parent category"),
    )
    description = models.TextField(_("description"), blank=True, default="")
    is_active = models.BooleanField(_("is active"), default=True)
    sort_order = models.PositiveIntegerField(_("sort order"), default=0)

    class Meta:
        verbose_name = _("category")
        verbose_name_plural = _("categories")
        ordering = ["sort_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "slug"],
                name="uniq_category_org_slug",
            ),
        ]

    def __str__(self) -> str:
        if self.parent:
            return f"{self.parent} > {self.name}"
        return self.name


class Unit(TenantModel):
    """Unit of measure (e.g. Piece, Box, Kilogram, Hour)."""

    name = models.CharField(_("unit name"), max_length=64)
    code = models.CharField(_("unit code"), max_length=16)
    precision = models.PositiveSmallIntegerField(
        _("decimal precision"),
        default=0,
        help_text=_(
            "Allowed decimal places for transaction quantities (0 for discrete pieces, 2-4 for weight/vol)."
        ),
    )
    is_active = models.BooleanField(_("is active"), default=True)

    class Meta:
        verbose_name = _("unit of measure")
        verbose_name_plural = _("units of measure")
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "code"],
                name="uniq_unit_org_code",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class UnitConversion(TenantModel):
    """Conversion factor between two units of measure (e.g. 1 Box = 12 Pieces)."""

    from_unit = models.ForeignKey(
        Unit,
        on_delete=models.CASCADE,
        related_name="conversions_from",
        verbose_name=_("from unit"),
    )
    to_unit = models.ForeignKey(
        Unit,
        on_delete=models.CASCADE,
        related_name="conversions_to",
        verbose_name=_("to unit"),
    )
    factor = models.DecimalField(
        _("conversion factor"),
        max_digits=18,
        decimal_places=6,
        help_text=_("Multiply quantity in from_unit by this factor to obtain quantity in to_unit."),
    )

    class Meta:
        verbose_name = _("unit conversion")
        verbose_name_plural = _("unit conversions")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "from_unit", "to_unit"],
                name="uniq_unit_conv_org_units",
            ),
        ]

    def __str__(self) -> str:
        return f"1 {self.from_unit.code} = {self.factor} {self.to_unit.code}"


class ProductType(models.TextChoices):
    """Classification of commercial catalog items."""

    STOCK = "stock", _("Physical Stock Item")
    SERVICE = "service", _("Service / Non-Stock")
    BUNDLE = "bundle", _("Product Bundle / Kit")


class Product(TenantModel):
    """Core commercial product item."""

    sku = models.CharField(_("SKU"), max_length=64)
    barcode = models.CharField(_("barcode / UPC / EAN"), max_length=64, blank=True, default="")
    name = models.CharField(_("product name"), max_length=255)
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
        verbose_name=_("category"),
    )
    unit = models.ForeignKey(
        Unit,
        on_delete=models.PROTECT,
        related_name="products",
        verbose_name=_("unit"),
    )
    type = models.CharField(
        _("product type"),
        max_length=16,
        choices=ProductType.choices,
        default=ProductType.STOCK,
    )
    cost_price = models.DecimalField(
        _("cost price"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    selling_price = models.DecimalField(
        _("selling price"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    tax_code = models.ForeignKey(
        "tenancy.TaxCode",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("tax code"),
    )
    track_batch = models.BooleanField(_("track batches"), default=False)
    track_serial = models.BooleanField(_("track serial numbers"), default=False)
    reorder_level = models.DecimalField(
        _("reorder level"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    reorder_quantity = models.DecimalField(
        _("reorder quantity"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    is_active = models.BooleanField(_("is active"), default=True)
    description = models.TextField(_("description"), blank=True, default="")

    class Meta:
        verbose_name = _("product")
        verbose_name_plural = _("products")
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "sku"],
                name="uniq_product_org_sku",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "barcode"]),
            models.Index(fields=["organization", "is_active", "type"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.sku})"

    @property
    def is_physical(self) -> bool:
        return self.type == ProductType.STOCK

    @property
    def margin_percent(self) -> Decimal:
        if self.cost_price and self.cost_price > Decimal("0"):
            return ((self.selling_price - self.cost_price) / self.cost_price) * Decimal("100")
        return Decimal("0.0000")


class ProductVariant(TenantModel):
    """Specific variant of a product (e.g. Size, Color)."""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="variants",
        verbose_name=_("product"),
    )
    sku = models.CharField(_("variant SKU"), max_length=64)
    barcode = models.CharField(_("variant barcode"), max_length=64, blank=True, default="")
    name = models.CharField(_("variant name"), max_length=128)
    attributes = models.JSONField(_("variant attributes"), default=dict, blank=True)
    cost_price_override = models.DecimalField(
        _("cost price override"),
        max_digits=18,
        decimal_places=4,
        null=True,
        blank=True,
    )
    selling_price_override = models.DecimalField(
        _("selling price override"),
        max_digits=18,
        decimal_places=4,
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(_("is active"), default=True)

    class Meta:
        base_manager_name = "all_tenants"
        verbose_name = _("product variant")
        verbose_name_plural = _("product variants")
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "sku"],
                name="uniq_variant_org_sku",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.product.name} - {self.name} ({self.sku})"

    @property
    def effective_cost_price(self) -> Decimal:
        return self.cost_price_override if self.cost_price_override is not None else self.product.cost_price

    @property
    def effective_selling_price(self) -> Decimal:
        return (
            self.selling_price_override
            if self.selling_price_override is not None
            else self.product.selling_price
        )


class ProductImage(TenantModel):
    """Gallery image linked to a product."""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="images",
        verbose_name=_("product"),
    )
    image = models.ImageField(_("image file"), upload_to="products/%Y/%m/")
    alt_text = models.CharField(_("alt text"), max_length=255, blank=True, default="")
    is_primary = models.BooleanField(_("is primary image"), default=False)
    sort_order = models.PositiveIntegerField(_("sort order"), default=0)

    class Meta:
        base_manager_name = "all_tenants"
        verbose_name = _("product image")
        verbose_name_plural = _("product images")
        ordering = ["-is_primary", "sort_order", "created_at"]

    def __str__(self) -> str:
        return f"Image for {self.product.name} ({self.alt_text or 'Image'})"


class PriceList(TenantModel):
    """Tiered or promotional price list (e.g. Retail, Wholesale, VIP)."""

    name = models.CharField(_("price list name"), max_length=128)
    currency = models.CharField(_("currency code"), max_length=3, default="USD")
    is_default = models.BooleanField(_("is default price list"), default=False)
    is_active = models.BooleanField(_("is active"), default=True)
    description = models.CharField(_("description"), max_length=255, blank=True, default="")

    class Meta:
        verbose_name = _("price list")
        verbose_name_plural = _("price lists")
        ordering = ["-is_default", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="uniq_pricelist_org_name",
            ),
        ]

    def __str__(self) -> str:
        default_tag = " (Default)" if self.is_default else ""
        return f"{self.name}{default_tag} [{self.currency}]"


class PriceListItem(TenantModel):
    """Explicit item pricing rule within a price list."""

    price_list = models.ForeignKey(
        PriceList,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name=_("price list"),
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="price_list_items",
        verbose_name=_("product"),
    )
    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="price_list_items",
        verbose_name=_("variant"),
    )
    price = models.DecimalField(_("override price"), max_digits=18, decimal_places=4)
    min_quantity = models.DecimalField(
        _("minimum quantity break"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("1.0000"),
    )

    class Meta:
        base_manager_name = "all_tenants"
        verbose_name = _("price list item")
        verbose_name_plural = _("price list items")
        ordering = ["min_quantity"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "price_list", "product", "variant", "min_quantity"],
                name="uniq_pricelist_item_rule",
            ),
        ]

    def __str__(self) -> str:
        var_text = f" ({self.variant.name})" if self.variant else ""
        return (
            f"{self.price_list.name}: {self.product.name}{var_text} @ {self.price} (min {self.min_quantity})"
        )
