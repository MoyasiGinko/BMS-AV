"""DRF API routing for customers, addresses, contacts, and subledgers."""

from __future__ import annotations

from rest_framework.routers import DefaultRouter

from apps.customers.api.views import (
    CustomerAddressViewSet,
    CustomerBalanceEntryViewSet,
    CustomerContactViewSet,
    CustomerViewSet,
)

router = DefaultRouter()
router.register("accounts", CustomerViewSet, basename="customer-accounts")
router.register("addresses", CustomerAddressViewSet, basename="customer-addresses")
router.register("contacts", CustomerContactViewSet, basename="customer-contacts")
router.register("entries", CustomerBalanceEntryViewSet, basename="customer-entries")

urlpatterns = router.urls
