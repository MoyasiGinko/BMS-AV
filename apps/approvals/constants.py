"""Constants and TextChoices for the Approvals engine."""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


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
