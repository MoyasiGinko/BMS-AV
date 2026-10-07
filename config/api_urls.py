"""Versioned REST API (/api/v1/). Each module registers its routes here (see ADR 0001)."""

from django.urls import URLPattern, URLResolver

app_name = "api"

urlpatterns: list[URLPattern | URLResolver] = []
