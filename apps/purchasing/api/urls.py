"""API URL routing for Purchasing endpoints under /api/v1/purchasing/."""

from rest_framework.routers import DefaultRouter

from apps.purchasing.api.views import (
    GoodsReceiptViewSet,
    PurchaseOrderViewSet,
    PurchaseReturnViewSet,
    SupplierBillViewSet,
    SupplierPaymentViewSet,
    SupplierViewSet,
)

app_name = "purchasing_api"

router = DefaultRouter()
router.register("suppliers", SupplierViewSet, basename="supplier")
router.register("orders", PurchaseOrderViewSet, basename="purchase-order")
router.register("receipts", GoodsReceiptViewSet, basename="goods-receipt")
router.register("bills", SupplierBillViewSet, basename="supplier-bill")
router.register("payments", SupplierPaymentViewSet, basename="supplier-payment")
router.register("returns", PurchaseReturnViewSet, basename="purchase-return")

urlpatterns = router.urls
