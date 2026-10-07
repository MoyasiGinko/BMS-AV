"""Root URL configuration."""

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.core.views import healthz_view, readyz_view, styleguide_view

urlpatterns = [
    path("_styleguide/", styleguide_view, name="styleguide"),
    path("healthz", healthz_view, name="healthz"),
    path("healthz/", healthz_view),
    path("readyz", readyz_view, name="readyz"),
    path("readyz/", readyz_view),
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("accounts/2fa/", include("allauth.mfa.urls")),
    path("tenancy/", include("apps.tenancy.urls")),
    path("billing/", include("apps.billing.urls")),
    path("settings/", include("apps.tenancy.settings_urls")),
    path("api/v1/", include("config.api_urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="api-schema"), name="api-docs"),
]
