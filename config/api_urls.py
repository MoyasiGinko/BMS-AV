"""Versioned REST API (/api/v1/). Each module registers its routes here (see ADR 0001)."""

from django.urls import URLPattern, URLResolver, include, path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)

app_name = "api"

urlpatterns: list[URLPattern | URLResolver] = [
    # JWT authentication endpoints
    path("auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("auth/token/verify/", TokenVerifyView.as_view(), name="token_verify"),
    # Core platform foundation endpoints
    path("core/", include("apps.core.api.urls")),
    # Billing & plans
    path("billing/", include("apps.billing.api.urls")),
    # Product catalog
    path("catalog/", include("apps.catalog.api.urls")),
    # Inventory & stock ledger
    path("inventory/", include("apps.inventory.api.urls")),
    # Customer relationship & subledger
    path("customers/", include("apps.customers.api.urls")),
    # Sales & Invoicing
    path("sales/", include("apps.sales.api.urls")),
    # Point of Sale (POS)
    path("pos/", include("apps.pos.api.urls")),
]
