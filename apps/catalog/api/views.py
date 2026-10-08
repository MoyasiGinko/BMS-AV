"""DRF API ViewSets for catalog models."""

from __future__ import annotations

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
