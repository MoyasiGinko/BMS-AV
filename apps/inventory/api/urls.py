"""URL patterns for inventory REST API endpoints."""

from rest_framework.routers import DefaultRouter

from apps.inventory.api.views import (
    InventoryLocationViewSet,
    InventoryReconciliationViewSet,
    StockAdjustmentViewSet,
    StockLevelViewSet,
    StockMovementViewSet,
    StockReservationViewSet,
    StockSupplyRouteViewSet,
    StockTransferViewSet,
)

router = DefaultRouter()
router.register(r"locations", InventoryLocationViewSet, basename="inventory-location")
router.register(r"supply-routes", StockSupplyRouteViewSet, basename="stock-supply-route")
router.register(r"reconciliation", InventoryReconciliationViewSet, basename="inventory-reconciliation")
router.register(r"levels", StockLevelViewSet, basename="stock-level")
router.register(r"movements", StockMovementViewSet, basename="stock-movement")
router.register(r"transfers", StockTransferViewSet, basename="stock-transfer")
router.register(r"adjustments", StockAdjustmentViewSet, basename="stock-adjustment")
router.register(r"reservations", StockReservationViewSet, basename="stock-reservation")

urlpatterns = router.urls
