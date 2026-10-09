"""REST API URL routing for the Point of Sale (POS) module."""

from rest_framework.routers import DefaultRouter

from apps.pos.api import views

router = DefaultRouter()
router.register("registers", views.POSRegisterViewSet, basename="register")
router.register("shifts", views.POSShiftViewSet, basename="shift")
router.register("sales", views.POSSaleViewSet, basename="sale")
router.register("held-carts", views.POSHeldCartViewSet, basename="held-cart")

urlpatterns = router.urls
