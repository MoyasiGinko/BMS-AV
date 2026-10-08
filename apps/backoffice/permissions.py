"""Permissions and access control for the Back-Office control plane."""

from collections.abc import Callable
from functools import wraps
from typing import Any

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect


def is_staff_user(user: Any) -> bool:
    """Return True if user is authenticated and is staff or superuser."""
    return bool(user and getattr(user, "is_authenticated", False) and (user.is_staff or user.is_superuser))


def staff_required(view_func: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """Decorator requiring authenticated internal staff or superuser."""

    @wraps(view_func)
    def _wrapped_view(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not getattr(request.user, "is_authenticated", False):
            return redirect(f"/accounts/login/?next={request.get_full_path()}")
        if not (request.user.is_staff or request.user.is_superuser):
            raise PermissionDenied("Internal staff credentials are required to access the Back-Office.")
        return view_func(request, *args, **kwargs)

    return _wrapped_view
