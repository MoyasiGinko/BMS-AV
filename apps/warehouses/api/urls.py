"""URL routing for the Warehouses REST API."""

from rest_framework.routers import DefaultRouter

from apps.warehouses.api import views

app_name = "warehouses_api"

router = DefaultRouter()
router.register("facilities", views.WarehouseViewSet, basename="facility")
router.register("branch-allocations", views.BranchWarehouseViewSet, basename="branch_allocation")
router.register("locations", views.InventoryLocationViewSet, basename="location")
router.register("supply-routes", views.StockSupplyRouteViewSet, basename="supply_route")

urlpatterns = router.urls
