"""Approvals engine views: inbox, request details, approve/reject actions, and rule management."""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.approvals import selectors, services
from apps.approvals.exceptions import (
    ApprovalsException,
    InvalidApprovalStateError,
    UnauthorizedApproverError,
)
from apps.approvals.forms import (
    ApprovalDecisionForm,
    ApprovalFilterForm,
    ApprovalRuleForm,
)
from apps.approvals.models import (
    ApprovalRequest,
    ApprovalRule,
    ApprovalRuleType,
    ApprovalStatus,
)
from apps.core.permissions import permission_required
from apps.core.tenant_context import get_current_organization


@login_required
@permission_required("approvals.view")
def inbox(request: HttpRequest) -> HttpResponse:
    """Approval Inbox: overview of requests with filtering and quick decision triggers."""
    org = get_current_organization()
    filter_form = ApprovalFilterForm(request.GET)

    status_filter = request.GET.get("status", ApprovalStatus.PENDING)
    if status_filter == "all":
        status_filter = ""
    doc_type_filter = request.GET.get("document_type", "")
    search_query = request.GET.get("search", "")

    requests_qs = selectors.list_approval_requests(
        organization=org,
        user=request.user,
        status=status_filter or None,
        document_type=doc_type_filter or None,
        search=search_query or None,
    )

    pending_count = selectors.get_pending_approval_count(organization=org)
    all_requests = ApprovalRequest.all_tenants.filter(organization=org)
    approved_count = all_requests.filter(status=ApprovalStatus.APPROVED).count()
    rejected_count = all_requests.filter(status=ApprovalStatus.REJECTED).count()

    context = {
        "requests": requests_qs,
        "filter_form": filter_form,
        "current_status": status_filter,
        "current_doc_type": doc_type_filter,
        "search_query": search_query,
        "pending_count": pending_count,
        "approved_count": approved_count,
        "rejected_count": rejected_count,
        "doc_types": ApprovalRuleType.choices,
        "statuses": ApprovalStatus.choices,
    }

    if request.headers.get("HX-Request") and request.GET.get("partial") == "table":
        return render(request, "approvals/partials/inbox_table.html", context)

    return render(request, "approvals/inbox.html", context)


@login_required
@permission_required("approvals.view")
def request_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Detailed view of an approval request with audit timeline and decision actions."""
    org = get_current_organization()
    req = selectors.get_approval_request(organization=org, pk=pk)
    if not req:
        messages.error(request, _("Approval request not found."))
        return redirect("approvals:inbox")

    can_approve = services.check_can_approve(
        organization=org,
        actor=request.user,
        request=req,
    )

    context = {
        "approval_request": req,
        "history": req.history.all(),
        "can_approve": can_approve,
        "decision_form": ApprovalDecisionForm(),
    }
    return render(request, "approvals/request_detail.html", context)


@login_required
@require_POST
@permission_required("approvals.approve")
def request_approve(request: HttpRequest, pk: int) -> HttpResponse:
    """Approve a pending approval request."""
    org = get_current_organization()
    req = selectors.get_approval_request(organization=org, pk=pk)
    if not req:
        messages.error(request, _("Approval request not found."))
        return redirect("approvals:inbox")

    notes = request.POST.get("notes", "")

    try:
        services.approve_request(
            organization=org,
            actor=request.user,
            request=req,
            notes=notes,
        )
        messages.success(request, _("Request %s has been successfully approved.") % req.document_reference)
    except (InvalidApprovalStateError, UnauthorizedApproverError, ApprovalsException, ValidationError) as e:
        messages.error(request, str(e))

    if request.headers.get("HX-Request"):
        # Re-fetch updated request and return partial
        req = selectors.get_approval_request(organization=org, pk=pk)
        return render(
            request,
            "approvals/partials/request_row.html",
            {
                "req": req,
                "can_approve": services.check_can_approve(organization=org, actor=request.user, request=req),
            },
        )

    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or "approvals:inbox"
    return redirect(next_url)


@login_required
@require_POST
@permission_required("approvals.approve")
def request_reject(request: HttpRequest, pk: int) -> HttpResponse:
    """Reject a pending approval request."""
    org = get_current_organization()
    req = selectors.get_approval_request(organization=org, pk=pk)
    if not req:
        messages.error(request, _("Approval request not found."))
        return redirect("approvals:inbox")

    notes = request.POST.get("notes", "")

    try:
        services.reject_request(
            organization=org,
            actor=request.user,
            request=req,
            notes=notes,
        )
        messages.warning(request, _("Request %s has been rejected.") % req.document_reference)
    except (InvalidApprovalStateError, UnauthorizedApproverError, ApprovalsException, ValidationError) as e:
        messages.error(request, str(e))

    if request.headers.get("HX-Request"):
        req = selectors.get_approval_request(organization=org, pk=pk)
        return render(
            request,
            "approvals/partials/request_row.html",
            {
                "req": req,
                "can_approve": services.check_can_approve(organization=org, actor=request.user, request=req),
            },
        )

    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or "approvals:inbox"
    return redirect(next_url)


@login_required
@require_POST
@permission_required("approvals.view")
def request_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    """Cancel a pending approval request."""
    org = get_current_organization()
    req = selectors.get_approval_request(organization=org, pk=pk)
    if not req:
        messages.error(request, _("Approval request not found."))
        return redirect("approvals:inbox")

    notes = request.POST.get("notes", "")

    try:
        services.cancel_request(
            organization=org,
            actor=request.user,
            request=req,
            notes=notes,
        )
        messages.info(request, _("Request %s has been cancelled.") % req.document_reference)
    except (InvalidApprovalStateError, UnauthorizedApproverError, ApprovalsException, ValidationError) as e:
        messages.error(request, str(e))

    return redirect("approvals:inbox")


# ---------------------------------------------------------------------------
# Rule Configuration Views
# ---------------------------------------------------------------------------


@login_required
@permission_required("approvals.manage")
def rule_list(request: HttpRequest) -> HttpResponse:
    """List configured approval rules for this organization."""
    org = get_current_organization()
    rules = selectors.list_approval_rules(organization=org)
    return render(request, "approvals/rule_list.html", {"rules": rules})


@login_required
@permission_required("approvals.manage")
def rule_create(request: HttpRequest) -> HttpResponse:
    """Create a new approval rule."""
    org = get_current_organization()

    if request.method == "POST":
        form = ApprovalRuleForm(request.POST, organization=org)
        if form.is_valid():
            try:
                rule = services.create_approval_rule(
                    organization=org,
                    actor=request.user,
                    name=form.cleaned_data["name"],
                    rule_type=form.cleaned_data["rule_type"],
                    min_amount=form.cleaned_data["min_amount"],
                    min_discount_percent=form.cleaned_data["min_discount_percent"],
                    approver_role=form.cleaned_data["approver_role"],
                    approver_user=form.cleaned_data["approver_user"],
                    is_active=form.cleaned_data["is_active"],
                    sort_order=form.cleaned_data["sort_order"],
                    description=form.cleaned_data["description"],
                )
                messages.success(request, _("Approval rule '%s' created successfully.") % rule.name)
                return redirect("approvals:rule_list")
            except (ApprovalsException, ValidationError) as e:
                messages.error(request, str(e))
    else:
        form = ApprovalRuleForm(organization=org)

    return render(request, "approvals/rule_form.html", {"form": form, "is_new": True})


@login_required
@permission_required("approvals.manage")
def rule_edit(request: HttpRequest, pk: int) -> HttpResponse:
    """Edit an existing approval rule."""
    org = get_current_organization()
    rule = selectors.get_approval_rule(organization=org, pk=pk)
    if not rule:
        messages.error(request, _("Approval rule not found."))
        return redirect("approvals:rule_list")

    if request.method == "POST":
        form = ApprovalRuleForm(request.POST, instance=rule, organization=org)
        if form.is_valid():
            try:
                services.update_approval_rule(
                    organization=org,
                    actor=request.user,
                    rule=rule,
                    name=form.cleaned_data["name"],
                    rule_type=form.cleaned_data["rule_type"],
                    min_amount=form.cleaned_data["min_amount"],
                    min_discount_percent=form.cleaned_data["min_discount_percent"],
                    approver_role=form.cleaned_data["approver_role"],
                    approver_user=form.cleaned_data["approver_user"],
                    is_active=form.cleaned_data["is_active"],
                    sort_order=form.cleaned_data["sort_order"],
                    description=form.cleaned_data["description"],
                )
                messages.success(request, _("Approval rule '%s' updated successfully.") % rule.name)
                return redirect("approvals:rule_list")
            except (ApprovalsException, ValidationError) as e:
                messages.error(request, str(e))
    else:
        form = ApprovalRuleForm(instance=rule, organization=org)

    return render(request, "approvals/rule_form.html", {"form": form, "rule": rule, "is_new": False})


@login_required
@require_POST
@permission_required("approvals.manage")
def rule_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Delete an approval rule."""
    org = get_current_organization()
    rule = selectors.get_approval_rule(organization=org, pk=pk)
    if not rule:
        messages.error(request, _("Approval rule not found."))
        return redirect("approvals:rule_list")

    name = rule.name
    services.delete_approval_rule(organization=org, actor=request.user, rule=rule)
    messages.info(request, _("Approval rule '%s' deleted.") % name)
    return redirect("approvals:rule_list")


@login_required
@permission_required("approvals.view")
def history_list(request: HttpRequest) -> HttpResponse:
    """List historical audit records for the organization's approval engine."""
    org = get_current_organization()
    history = selectors.list_approval_history(organization=org)
    return render(request, "approvals/history_list.html", {"history": history})
