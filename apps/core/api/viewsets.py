"""Base tenant-scoped DRF viewsets for Business OS.

Guarantees tenant isolation, 3-layer authorization, actor injection,
and automatic queryset scoping for all API endpoints.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from django.apps import apps
from django.db.models import QuerySet
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.core.api.pagination import StandardCursorPagination
from apps.core.api.permissions import (
    HasFeatureEntitlement,
    HasObjectScope,
    HasRolePermission,
)
from apps.core.api.throttling import TenantAnonRateThrottle, TenantUserRateThrottle
from apps.core.exceptions import TenantAccessError
from apps.core.permissions import scope_queryset
from apps.core.tenant_context import set_current_organization

logger = logging.getLogger(__name__)


class TenantScopedViewSet(viewsets.GenericViewSet):
    """Base ViewSet ensuring strict tenant scoping and 3-layer security checks."""

    module_key: str | None = None
    permission_map: dict[str, str] = {}
    required_permission: str | None = None

    permission_classes = [
        IsAuthenticated,
        HasFeatureEntitlement,
        HasRolePermission,
        HasObjectScope,
    ]
    throttle_classes = [TenantUserRateThrottle, TenantAnonRateThrottle]
    pagination_class = StandardCursorPagination

    def initial(self, request: Any, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        try:
            org = self.get_tenant()
            set_current_organization(org)
        except Exception as exc:
            logger.debug("Tenant initialization deferred in initial(): %s", exc)

    def get_tenant(self) -> Any:
        """Resolve and validate the active organization for the current request."""
        request = self.request
        user = getattr(request, "user", None)

        # 1. Header override (X-Organization-ID or X-Tenant-ID)
        header_val = (
            request.headers.get("X-Organization-ID")
            or request.headers.get("X-Tenant-ID")
            or request.META.get("HTTP_X_ORGANIZATION_ID")
            or request.META.get("HTTP_X_TENANT_ID")
        )
        if header_val and apps.is_installed("apps.tenancy"):
            org = self._resolve_org_by_identifier(str(header_val).strip())
            if org is not None:
                self._validate_membership(user, org)
                request.organization = org  # type: ignore[attr-defined]
                set_current_organization(org)
                return org

        # 2. Existing request.organization resolved by TenantMiddleware
        org = getattr(request, "organization", None)
        if org is not None:
            self._validate_membership(user, org)
            return org

        # 3. User default membership fallback
        if user and user.is_authenticated and apps.is_installed("apps.tenancy"):
            org = self._resolve_org_from_user(user)
            if org is not None:
                request.organization = org  # type: ignore[attr-defined]
                set_current_organization(org)
                return org

        raise TenantAccessError("Active organization context is missing or not specified.")

    def _resolve_org_by_identifier(self, identifier: str) -> Any | None:
        """Lookup organization by UUID public_id, numeric ID, or slug."""
        try:
            org_model: Any = apps.get_app_config("tenancy").get_model("Organization")
            if not org_model:
                return None

            try:
                parsed_uuid = uuid.UUID(identifier)
                return org_model.objects.filter(public_id=parsed_uuid, is_active=True).first()
            except ValueError:
                pass

            if identifier.isdigit():
                return org_model.objects.filter(id=int(identifier), is_active=True).first()

            return org_model.objects.filter(slug=identifier, is_active=True).first()
        except LookupError:
            return None

    def _resolve_org_from_user(self, user: Any) -> Any | None:
        """Find the user's active organization via Membership."""
        try:
            membership_model: Any = apps.get_app_config("tenancy").get_model("Membership")
            if not membership_model:
                return None
            membership = (
                membership_model.all_tenants.filter(user=user, organization__is_active=True)
                .select_related("organization")
                .first()
            )
            if membership and membership.organization:
                return membership.organization
        except LookupError:
            pass
        return None

    def _validate_membership(self, user: Any, org: Any) -> None:
        """Ensure authenticated user is a valid active member of the target organization."""
        if not user or not user.is_authenticated:
            return

        if getattr(user, "is_superuser", False) or getattr(user, "is_staff", False):
            return

        try:
            membership_model: Any = apps.get_app_config("tenancy").get_model("Membership")
            if not membership_model:
                return
            is_member = membership_model.all_tenants.filter(
                user=user,
                organization=org,
                status="active",
            ).exists()
            if not is_member:
                raise TenantAccessError("You are not an active member of this organization.")
        except LookupError:
            pass

    def get_queryset(self) -> QuerySet[Any]:
        """Scope queryset strictly to the active tenant and user branch/warehouse scope."""
        org = self.get_tenant()
        set_current_organization(org)

        raw_qs: QuerySet[Any] = super().get_queryset()
        model: Any = getattr(raw_qs, "model", None)
        if model is not None:
            mgr: Any = getattr(model, "all_tenants", None)
            if mgr is None and hasattr(model, "_meta"):
                mgr = getattr(model._meta, "default_manager", None)
            qs: QuerySet[Any] = mgr.all() if mgr is not None else raw_qs
        else:
            qs = raw_qs

        # If model has an organization field, guarantee it is scoped to current org
        if hasattr(qs, "model") and any(f.name == "organization" for f in qs.model._meta.get_fields()):
            qs = qs.filter(organization=org)

        # Layer 3: Apply object branch/warehouse scope
        if hasattr(self.request, "user") and self.request.user.is_authenticated:
            qs = scope_queryset(qs, self.request.user, organization=org)

        return qs

    def perform_create(self, serializer: Any) -> None:
        """Automatically inject organization and created_by actor on creation."""
        org = self.get_tenant()
        save_kwargs: dict[str, Any] = {}

        model = getattr(serializer.Meta, "model", None)
        if model:
            field_names = {f.name for f in model._meta.get_fields()}
            if "organization" in field_names and "organization" not in serializer.validated_data:
                save_kwargs["organization"] = org
            if (
                "created_by" in field_names
                and "created_by" not in serializer.validated_data
                and self.request.user.is_authenticated
            ):
                save_kwargs["created_by"] = self.request.user

        serializer.save(**save_kwargs)

    def perform_update(self, serializer: Any) -> None:
        """Optionally inject updated_by actor on update."""
        save_kwargs: dict[str, Any] = {}
        model = getattr(serializer.Meta, "model", None)
        if model:
            field_names = {f.name for f in model._meta.get_fields()}
            if (
                "updated_by" in field_names
                and "updated_by" not in serializer.validated_data
                and self.request.user.is_authenticated
            ):
                save_kwargs["updated_by"] = self.request.user

        serializer.save(**save_kwargs)


class TenantScopedModelViewSet(TenantScopedViewSet, viewsets.ModelViewSet):
    """Convenience class combining TenantScopedViewSet with standard CRUD ModelViewSet."""

    pass


class TenantScopedReadOnlyModelViewSet(TenantScopedViewSet, viewsets.ReadOnlyModelViewSet):
    """Convenience class combining TenantScopedViewSet with ReadOnlyModelViewSet."""

    pass
