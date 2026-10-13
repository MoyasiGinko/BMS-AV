"""Approvals Engine data models: ApprovalRule, ApprovalRequest, ApprovalHistory."""

from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantModel


class ApprovalRuleType(models.TextChoices):
    PURCHASE_ORDER = "purchase_order", _("Purchase Order")
    EXPENSE = "expense", _("Expense")
    PAYROLL = "payroll", _("Payroll Run")
    DISCOUNT = "discount", _("Sales Discount")


class ApprovalStatus(models.TextChoices):
    PENDING = "pending", _("Pending Approval")
    APPROVED = "approved", _("Approved")
    REJECTED = "rejected", _("Rejected")
    CANCELLED = "cancelled", _("Cancelled")


class ApprovalAction(models.TextChoices):
    SUBMITTED = "submitted", _("Submitted")
    APPROVED = "approved", _("Approved")
    REJECTED = "rejected", _("Rejected")
    CANCELLED = "cancelled", _("Cancelled")


class ApprovalRule(TenantModel):
    """Configurable tenant-level approval policy rule."""

    name = models.CharField(_("rule name"), max_length=255)
    rule_type = models.CharField(
        _("rule type"),
        max_length=32,
        choices=ApprovalRuleType.choices,
    )
    description = models.TextField(_("description"), blank=True)
    min_amount = models.DecimalField(
        _("minimum amount threshold"),
        max_digits=14,
        decimal_places=4,
        default=Decimal("0.0000"),
        help_text=_("Trigger approval when document total amount is greater than or equal to this amount."),
    )
    min_discount_percent = models.DecimalField(
        _("minimum discount percentage threshold"),
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text=_("Trigger approval when sales discount percentage is greater than or equal to this percentage."),
    )
    approver_role = models.ForeignKey(
        "tenancy.Role",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_rules",
        verbose_name=_("assigned approver role"),
        help_text=_("Designated role authorized to approve or reject this request. If blank, any authorized user can approve."),
    )
    approver_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_approval_rules",
        verbose_name=_("assigned approver user"),
        help_text=_("Specific user assigned to approve. If blank, any member with the approver role can approve."),
    )
    is_active = models.BooleanField(_("active"), default=True)
    sort_order = models.PositiveIntegerField(_("sort order / priority"), default=10)

    class Meta:
        verbose_name = _("approval rule")
        verbose_name_plural = _("approval rules")
        ordering = ["sort_order", "id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="uniq_approval_rule_name_per_org",
            )
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "rule_type", "is_active"]),
            models.Index(fields=["organization", "sort_order"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_rule_type_display()})"


class ApprovalRequest(TenantModel):
    """An individual approval request instance for a specific business document."""

    rule = models.ForeignKey(
        ApprovalRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requests",
        verbose_name=_("matched approval rule"),
    )
    document_type = models.CharField(
        _("document type"),
        max_length=32,
        choices=ApprovalRuleType.choices,
    )
    document_id = models.CharField(
        _("document ID"),
        max_length=64,
        help_text=_("Primary identifier of the business document requiring approval."),
    )
    document_reference = models.CharField(
        _("document reference"),
        max_length=128,
        help_text=_("Human-readable reference number (e.g. PO-2026-0001)."),
    )
    document_title = models.CharField(
        _("document title"),
        max_length=255,
        help_text=_("Brief descriptive title or context for this approval request."),
    )
    amount = models.DecimalField(
        _("amount"),
        max_digits=14,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    discount_percent = models.DecimalField(
        _("discount percentage"),
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    status = models.CharField(
        _("approval status"),
        max_length=20,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING,
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="submitted_approval_requests",
        verbose_name=_("requester"),
    )
    assigned_role = models.ForeignKey(
        "tenancy.Role",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_approval_requests",
        verbose_name=_("assigned approver role"),
    )
    assigned_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_approval_requests",
        verbose_name=_("assigned approver user"),
    )
    submission_notes = models.TextField(_("submission notes"), blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_approval_requests",
        verbose_name=_("reviewed by"),
    )
    reviewed_at = models.DateTimeField(_("reviewed at"), null=True, blank=True)
    decision_notes = models.TextField(_("decision notes"), blank=True)

    class Meta:
        verbose_name = _("approval request")
        verbose_name_plural = _("approval requests")
        ordering = ["-created_at"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "status", "-created_at"]),
            models.Index(fields=["organization", "document_type", "document_id"]),
            models.Index(fields=["organization", "requester"]),
        ]

    def __str__(self) -> str:
        return f"{self.document_reference} ({self.get_document_type_display()} - {self.get_status_display()})"


class ApprovalHistory(TenantModel):
    """Chronological, immutable audit record of actions taken on an approval request."""

    request = models.ForeignKey(
        ApprovalRequest,
        on_delete=models.CASCADE,
        related_name="history",
        verbose_name=_("approval request"),
    )
    action = models.CharField(
        _("action taken"),
        max_length=20,
        choices=ApprovalAction.choices,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_history_actions",
        verbose_name=_("action actor"),
    )
    notes = models.TextField(_("notes / reason"), blank=True)

    class Meta:
        verbose_name = _("approval history entry")
        verbose_name_plural = _("approval history entries")
        ordering = ["created_at"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "request", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.request.document_reference}: {self.get_action_display()} at {self.created_at}"
