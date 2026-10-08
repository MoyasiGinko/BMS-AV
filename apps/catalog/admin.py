"""Django admin registration for catalog models."""

from __future__ import annotations

from django.contrib import admin

from apps.catalog.models import (
    Category,
    PriceList,
    PriceListItem,
    Product,
    ProductImage,
    ProductVariant,
    Unit,
    UnitConversion,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "parent", "is_active", "sort_order", "organization")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "precision", "is_active", "organization")
    list_filter = ("is_active",)
    search_fields = ("name", "code")


@admin.register(UnitConversion)
class UnitConversionAdmin(admin.ModelAdmin):
    list_display = ("from_unit", "to_unit", "factor", "organization")
    search_fields = ("from_unit__name", "to_unit__name")


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "sku",
        "name",
        "category",
        "unit",
        "type",
        "selling_price",
        "cost_price",
        "is_active",
        "organization",
    )
    list_filter = ("type", "is_active", "category")
    search_fields = ("sku", "barcode", "name")
    inlines = [ProductVariantInline, ProductImageInline]


class PriceListItemInline(admin.TabularInline):
    model = PriceListItem
    extra = 0
    autocomplete_fields = ["product"]


@admin.register(PriceList)
class PriceListAdmin(admin.ModelAdmin):
    list_display = ("name", "currency", "is_default", "is_active", "organization")
    list_filter = ("is_default", "is_active", "currency")
    search_fields = ("name",)
    inlines = [PriceListItemInline]
