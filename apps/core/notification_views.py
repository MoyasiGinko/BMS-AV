"""Views for the In-App Notifications Center and User Notification Preferences."""

from __future__ import annotations

import logging
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core import notifications, selectors
from apps.core.models import NotificationChannel, NotificationStatus
from apps.core.tenant_context import get_current_organization

logger = logging.getLogger(__name__)

STANDARD_NOTIFICATION_CATEGORIES = [
    ("approvals", _("Approvals & Workflows"), _("Document approval requests, rejections, and approvals")),
    ("billing", _("Invoices & Billing"), _("Invoices generated, payment receipts, subscription renewals")),
    (
        "inventory",
        _("Inventory & Reorder Alerts"),
        _("Stock dropping below reorder point, batch expirations"),
    ),
    ("sales", _("Sales & Orders"), _("High-value orders, customer quotes, fulfillment updates")),
    ("security", _("Security & Team"), _("New logins, role permission alterations, API key actions")),
    ("payroll", _("Payroll & HR"), _("Salary run approvals, payslip releases, leave requests")),
    ("system", _("System & Portability"), _("Data exports ready, import completions, scheduled tasks")),
]


def _get_active_org(request: HttpRequest) -> Any:
    org = getattr(request, "organization", None) or get_current_organization()
    return org


@login_required
def notification_center_view(request: HttpRequest) -> HttpResponse:
    """Primary Notifications Center listing alerts with category and status filtering."""
    org = _get_active_org(request)
    if not org:
        return redirect("/tenancy/select/")

    user = request.user
    active_tab = request.GET.get("tab", "all").strip().lower()
    active_category = request.GET.get("category", "").strip().lower()
    search_q = request.GET.get("q", "").strip()

    status_filter = None
    unread_only = False
    if active_tab == "unread":
        unread_only = True
    elif active_tab == "read":
        status_filter = NotificationStatus.READ

    category_filter = active_category if active_category else None

    notifications_qs = selectors.list_user_notifications(
        organization_id=org.pk,
        user=user,
        status=status_filter,
        category=category_filter,
        unread_only=unread_only,
    )

    if search_q:
        notifications_qs = notifications_qs.filter(title__icontains=search_q)

    paginator = Paginator(notifications_qs, 25)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    unread_count = selectors.get_unread_notifications_count(
        organization_id=org.pk,
        user=user,
    )

    context = {
        "organization": org,
        "page_obj": page_obj,
        "notifications": page_obj.object_list,
        "unread_count": unread_count,
        "active_tab": active_tab,
        "active_category": active_category,
        "categories": STANDARD_NOTIFICATION_CATEGORIES,
        "search_q": search_q,
    }

    if request.headers.get("HX-Request") and request.GET.get("partial") == "list":
        return render(request, "notifications/partials/notification_list.html", context)

    return render(request, "notifications/center.html", context)


@login_required
def notification_unread_count_view(request: HttpRequest) -> HttpResponse:
    """HTMX endpoint returning the badge snippet for the top-bar bell."""
    org = _get_active_org(request)
    if not org:
        return HttpResponse("")

    unread_count = selectors.get_unread_notifications_count(
        organization_id=org.pk,
        user=request.user,
    )
    return render(
        request,
        "notifications/partials/unread_badge.html",
        {"unread_count": unread_count},
    )


@login_required
def notification_preview_view(request: HttpRequest) -> HttpResponse:
    """HTMX dropdown popover previewing recent unread notifications."""
    org = _get_active_org(request)
    if not org:
        return HttpResponse("")

    user = request.user
    recent_notifications = selectors.list_user_notifications(
        organization_id=org.pk,
        user=user,
        channel=NotificationChannel.IN_APP,
    )[:5]

    unread_count = selectors.get_unread_notifications_count(
        organization_id=org.pk,
        user=user,
    )

    context = {
        "notifications": recent_notifications,
        "unread_count": unread_count,
        "organization": org,
    }
    return render(request, "notifications/partials/dropdown_preview.html", context)


@login_required
@require_POST
def notification_mark_read_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """Mark a specific notification as read."""
    org = _get_active_org(request)
    if not org:
        return HttpResponseForbidden()

    notif = notifications.mark_notification_read(
        notification_id=public_id,
        organization_id=org.pk,
        user=request.user,
    )

    if request.headers.get("HX-Request"):
        if notif:
            response = render(
                request,
                "notifications/partials/notification_item.html",
                {"item": notif},
            )
            response["HX-Trigger"] = "refreshUnreadCount"
            return response
        return HttpResponse(status=404)

    messages.success(request, _("Notification marked as read."))
    return redirect("notifications:center")


@login_required
@require_POST
def notification_mark_unread_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """Mark a specific notification as unread."""
    org = _get_active_org(request)
    if not org:
        return HttpResponseForbidden()

    notif = notifications.mark_notification_unread(
        notification_id=public_id,
        organization_id=org.pk,
        user=request.user,
    )

    if request.headers.get("HX-Request"):
        if notif:
            response = render(
                request,
                "notifications/partials/notification_item.html",
                {"item": notif},
            )
            response["HX-Trigger"] = "refreshUnreadCount"
            return response
        return HttpResponse(status=404)

    messages.success(request, _("Notification marked as unread."))
    return redirect("notifications:center")


@login_required
@require_POST
def notification_mark_all_read_view(request: HttpRequest) -> HttpResponse:
    """Mark all unread notifications for this user in this organization as read."""
    org = _get_active_org(request)
    if not org:
        return HttpResponseForbidden()

    count = notifications.mark_all_notifications_read(
        organization_id=org.pk,
        user=request.user,
    )

    if request.headers.get("HX-Request"):
        notifications_qs = selectors.list_user_notifications(
            organization_id=org.pk,
            user=request.user,
        )[:25]
        response = render(
            request,
            "notifications/partials/notification_list.html",
            {
                "notifications": notifications_qs,
                "unread_count": 0,
                "organization": org,
                "active_tab": "all",
            },
        )
        response["HX-Trigger"] = "refreshUnreadCount"
        return response

    messages.success(request, _("%(count)d notifications marked as read.") % {"count": count})
    return redirect("notifications:center")


@login_required
@require_POST
def notification_delete_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """Delete a notification permanently."""
    org = _get_active_org(request)
    if not org:
        return HttpResponseForbidden()

    deleted = notifications.delete_notification(
        organization_id=org.pk,
        notification_id=public_id,
        user=request.user,
    )

    if request.headers.get("HX-Request"):
        response = HttpResponse("")
        response["HX-Trigger"] = "refreshUnreadCount"
        return response

    if deleted:
        messages.success(request, _("Notification removed."))
    return redirect("notifications:center")


@login_required
def user_notification_preferences_view(request: HttpRequest) -> HttpResponse:
    """Configure personal notification channel preferences per category."""
    org = _get_active_org(request)
    if not org:
        return redirect("/tenancy/select/")

    user = request.user

    if request.method == "POST":
        for cat_key, _label, _desc in STANDARD_NOTIFICATION_CATEGORIES:
            email_val = request.POST.get(f"{cat_key}_email") == "on"
            in_app_val = request.POST.get(f"{cat_key}_in_app") == "on"

            notifications.update_user_notification_preference(
                organization_id=org.pk,
                user=user,
                category=cat_key,
                channel=NotificationChannel.EMAIL,
                is_enabled=email_val,
                actor=user,
            )
            notifications.update_user_notification_preference(
                organization_id=org.pk,
                user=user,
                category=cat_key,
                channel=NotificationChannel.IN_APP,
                is_enabled=in_app_val,
                actor=user,
            )

        messages.success(request, _("Your notification preferences have been saved."))
        return redirect("notifications:preferences")

    user_pk = getattr(user, "pk", None)
    if not user_pk:
        return redirect("/accounts/login/")

    prefs_map = selectors.get_user_notification_preferences_map(
        organization_id=org.pk,
        user_id=int(user_pk),
    )

    category_items = []
    for cat_key, cat_label, cat_desc in STANDARD_NOTIFICATION_CATEGORIES:
        category_items.append(
            {
                "key": cat_key,
                "label": cat_label,
                "description": cat_desc,
                "email_enabled": prefs_map.get((cat_key, NotificationChannel.EMAIL), True),
                "in_app_enabled": prefs_map.get((cat_key, NotificationChannel.IN_APP), True),
            }
        )

    context = {
        "organization": org,
        "category_items": category_items,
    }
    return render(request, "notifications/user_preferences.html", context)
