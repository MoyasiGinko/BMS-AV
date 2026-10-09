"""DRF API ViewSets for catalog models."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema, extend_schema_view

from apps.catalog.api.serializers import (
    CategorySerializer,
    PriceListSerializer,
    ProductSerializer,
    UnitSerializer,
)
from apps.catalog.models import (
    Category,
    PriceList,
    Product,
    Unit,
)
from apps.core.api.viewsets import TenantScopedModelViewSet


@extend_schema_view(
    list=extend_schema(tags=["Catalog"], summary="List product categories"),
    retrieve=extend_schema(tags=["Catalog"], summary="Retrieve product category"),
    create=extend_schema(tags=["Catalog"], summary="Create product category"),
    update=extend_schema(tags=["Catalog"], summary="Update product category"),
    partial_update=extend_schema(tags=["Catalog"], summary="Partially update product category"),
    destroy=extend_schema(tags=["Catalog"], summary="Delete product category"),
)
class CategoryViewSet(TenantScopedModelViewSet):
    """API endpoint for managing product categories."""

    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    lookup_field = "public_id"
    module_key = "catalog"
    permission_map = {
        "list": "catalog.view",
        "retrieve": "catalog.view",
        "create": "catalog.manage",
        "update": "catalog.manage",
        "partial_update": "catalog.manage",
        "destroy": "catalog.manage",
    }
    search_fields = ["name", "slug"]
    ordering_fields = ["sort_order", "name"]
    ordering = ["sort_order", "name"]


@extend_schema_view(
    list=extend_schema(tags=["Catalog"], summary="List units of measure"),
    retrieve=extend_schema(tags=["Catalog"], summary="Retrieve unit of measure"),
    create=extend_schema(tags=["Catalog"], summary="Create unit of measure"),
    update=extend_schema(tags=["Catalog"], summary="Update unit of measure"),
    partial_update=extend_schema(tags=["Catalog"], summary="Partially update unit of measure"),
    destroy=extend_schema(tags=["Catalog"], summary="Delete unit of measure"),
)
class UnitViewSet(TenantScopedModelViewSet):
    """API endpoint for managing units of measure."""

    queryset = Unit.objects.all()
    serializer_class = UnitSerializer
    lookup_field = "public_id"
    module_key = "catalog"
    permission_map = {
        "list": "catalog.view",
        "retrieve": "catalog.view",
        "create": "catalog.manage",
        "update": "catalog.manage",
        "partial_update": "catalog.manage",
        "destroy": "catalog.manage",
    }
    search_fields = ["name", "code"]
    ordering_fields = ["name", "code"]
    ordering = ["name"]


@extend_schema_view(
    list=extend_schema(tags=["Catalog"], summary="List products and services"),
    retrieve=extend_schema(tags=["Catalog"], summary="Retrieve product or service"),
    create=extend_schema(tags=["Catalog"], summary="Create product or service"),
    update=extend_schema(tags=["Catalog"], summary="Update product or service"),
    partial_update=extend_schema(tags=["Catalog"], summary="Partially update product or service"),
    destroy=extend_schema(tags=["Catalog"], summary="Delete product or service"),
)
class ProductViewSet(TenantScopedModelViewSet):
    """API endpoint for products."""

    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    lookup_field = "public_id"
    module_key = "catalog"
    permission_map = {
        "list": "catalog.view",
        "retrieve": "catalog.view",
        "create": "catalog.manage",
        "update": "catalog.manage",
        "partial_update": "catalog.manage",
        "destroy": "catalog.manage",
    }
    filterset_fields = ["category", "type", "is_active"]
    search_fields = ["sku", "barcode", "name", "description"]
    ordering_fields = ["name", "sku", "selling_price", "created_at"]
    ordering = ["name"]


@extend_schema_view(
    list=extend_schema(tags=["Catalog"], summary="List customer price lists"),
    retrieve=extend_schema(tags=["Catalog"], summary="Retrieve price list"),
    create=extend_schema(tags=["Catalog"], summary="Create price list"),
    update=extend_schema(tags=["Catalog"], summary="Update price list"),
    partial_update=extend_schema(tags=["Catalog"], summary="Partially update price list"),
    destroy=extend_schema(tags=["Catalog"], summary="Delete price list"),
)
class PriceListViewSet(TenantScopedModelViewSet):
    """API endpoint for price lists."""

    queryset = PriceList.objects.all()
    serializer_class = PriceListSerializer
    lookup_field = "public_id"
    module_key = "catalog"
    permission_map = {
        "list": "catalog.view",
        "retrieve": "catalog.view",
        "create": "catalog.manage",
        "update": "catalog.manage",
        "partial_update": "catalog.manage",
        "destroy": "catalog.manage",
    }
    search_fields = ["name", "currency"]
    ordering_fields = ["name", "is_default"]
    ordering = ["-is_default", "name"]
