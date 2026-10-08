"""DRF API router configuration for catalog resources."""

from __future__ import annotations

from rest_framework.routers import DefaultRouter

from apps.catalog.api.views import (
    CategoryViewSet,
    PriceListViewSet,
    ProductViewSet,
    UnitViewSet,
)

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("units", UnitViewSet, basename="unit")
router.register("products", ProductViewSet, basename="product")
router.register("price-lists", PriceListViewSet, basename="pricelist")

urlpatterns = router.urls
