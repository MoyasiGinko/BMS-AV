"""Data models for CRM: Pipeline, Stage, Tag, Lead, Opportunity, Interaction, and Task."""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantModel


class Pipeline(TenantModel):
    """Sales opportunity pipeline representing a sales process."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    name = models.CharField(_("Pipeline Name"), max_length=128)
    code = models.SlugField(_("Code"), max_length=64)
    description = models.TextField(_("Description"), blank=True)
    is_default = models.BooleanField(_("Is Default"), default=False)
    is_active = models.BooleanField(_("Is Active"), default=True)

    class Meta:
        verbose_name = _("Pipeline")
        verbose_name_plural = _("Pipelines")
        ordering = ["-is_default", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "code"],
                name="uniq_crm_pipeline_org_code",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "is_active", "is_default"]),
        ]

    def __str__(self) -> str:
        return self.name


class Stage(TenantModel):
    """A distinct milestone or step within a sales pipeline."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    pipeline = models.ForeignKey(
        Pipeline,
        on_delete=models.CASCADE,
        related_name="stages",
        verbose_name=_("Pipeline"),
    )
    name = models.CharField(_("Stage Name"), max_length=64)
    code = models.SlugField(_("Code"), max_length=64)
    order = models.PositiveSmallIntegerField(_("Display Order"), default=0)
    probability_percent = models.PositiveSmallIntegerField(
        _("Win Probability (%)"),
        default=10,
        help_text=_("Estimated win probability (0-100)"),
    )
    is_won = models.BooleanField(_("Is Won Stage"), default=False)
    is_lost = models.BooleanField(_("Is Lost Stage"), default=False)

    class Meta:
        verbose_name = _("Pipeline Stage")
        verbose_name_plural = _("Pipeline Stages")
        ordering = ["pipeline", "order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "pipeline", "code"],
                name="uniq_crm_stage_pipeline_code",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "pipeline", "order"]),
        ]

    def __str__(self) -> str:
        return f"{self.pipeline.name} - {self.name}"


class Tag(TenantModel):
    """Categorization tag for labeling CRM entities (Leads, Opportunities, Customers)."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    name = models.CharField(_("Tag Name"), max_length=64)
    color = models.CharField(_("Hex Color"), max_length=16, default="#6366f1")

    class Meta:
        verbose_name = _("Tag")
        verbose_name_plural = _("Tags")
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="uniq_crm_tag_org_name",
            )
        ]

    def __str__(self) -> str:
        return self.name


class LeadStatus(models.TextChoices):
    NEW = "new", _("New")
    CONTACTED = "contacted", _("Contacted")
    QUALIFIED = "qualified", _("Qualified")
    UNQUALIFIED = "unqualified", _("Unqualified")
    CONVERTED = "converted", _("Converted")


class LeadSource(models.TextChoices):
    WEBSITE = "website", _("Website Form")
    REFERRAL = "referral", _("Referral")
    COLD_OUTREACH = "cold_outreach", _("Cold Outreach")
    EVENT = "event", _("Event / Conference")
    PARTNER = "partner", _("Partner Channel")
    OTHER = "other", _("Other")


class Lead(TenantModel):
    """Prospective customer before official account creation and commercial transactions."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    first_name = models.CharField(_("First Name"), max_length=64)
    last_name = models.CharField(_("Last Name"), max_length=64, blank=True)
    company_name = models.CharField(_("Company / Organization"), max_length=128, blank=True)
    email = models.EmailField(_("Email Address"), blank=True)
    phone = models.CharField(_("Phone Number"), max_length=32, blank=True)
    title = models.CharField(_("Job Title"), max_length=64, blank=True)
    status = models.CharField(
        _("Status"),
        max_length=32,
        choices=LeadStatus.choices,
        default=LeadStatus.NEW,
    )
    source = models.CharField(
        _("Lead Source"),
        max_length=32,
        choices=LeadSource.choices,
        default=LeadSource.WEBSITE,
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_leads",
        verbose_name=_("Assigned Sales Rep"),
    )
    estimated_value = models.DecimalField(
        _("Estimated Value"),
        max_digits=14,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    notes = models.TextField(_("Internal Notes"), blank=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name="leads")
    converted_customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="converted_leads",
        verbose_name=_("Converted Customer"),
    )
    converted_at = models.DateTimeField(_("Converted At"), null=True, blank=True)

    class Meta:
        verbose_name = _("Lead")
        verbose_name_plural = _("Leads")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "status", "-created_at"]),
            models.Index(fields=["organization", "assigned_to"]),
            models.Index(fields=["organization", "company_name"]),
        ]

    def __str__(self) -> str:
        full_name = f"{self.first_name} {self.last_name}".strip()
        if self.company_name:
            return f"{full_name} ({self.company_name})" if full_name else self.company_name
        return full_name or str(self.public_id)

    @property
    def full_name(self) -> str:
        name = f"{self.first_name} {self.last_name}".strip()
        return name or self.first_name or self.company_name

    @property
    def display_name(self) -> str:
        return str(self)


class OpportunityStatus(models.TextChoices):
    OPEN = "open", _("Open")
    WON = "won", _("Closed Won")
    LOST = "lost", _("Closed Lost")


class Opportunity(TenantModel):
    """Commercial sales deal tracked across pipeline stages."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    title = models.CharField(_("Deal Title"), max_length=128)
    pipeline = models.ForeignKey(
        Pipeline,
        on_delete=models.PROTECT,
        related_name="opportunities",
        verbose_name=_("Pipeline"),
    )
    stage = models.ForeignKey(
        Stage,
        on_delete=models.PROTECT,
        related_name="opportunities",
        verbose_name=_("Current Stage"),
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="opportunities",
        verbose_name=_("Customer Account"),
    )
    lead = models.ForeignKey(
        Lead,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="opportunities",
        verbose_name=_("Originating Lead"),
    )
    expected_value = models.DecimalField(
        _("Expected Value"),
        max_digits=14,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    currency = models.CharField(_("Currency"), max_length=3, default="USD")
    probability_percent = models.PositiveSmallIntegerField(
        _("Win Probability (%)"),
        default=50,
    )
    expected_close_date = models.DateField(_("Expected Close Date"), null=True, blank=True)
    actual_close_date = models.DateField(_("Actual Close Date"), null=True, blank=True)
    status = models.CharField(
        _("Status"),
        max_length=20,
        choices=OpportunityStatus.choices,
        default=OpportunityStatus.OPEN,
    )
    loss_reason = models.TextField(_("Loss Reason"), blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_opportunities",
        verbose_name=_("Deal Owner"),
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="opportunities")
    notes = models.TextField(_("Notes"), blank=True)

    class Meta:
        verbose_name = _("Opportunity")
        verbose_name_plural = _("Opportunities")
        ordering = ["-expected_value", "-created_at"]
        indexes = [
            models.Index(fields=["organization", "pipeline", "stage"]),
            models.Index(fields=["organization", "status", "-expected_close_date"]),
            models.Index(fields=["organization", "customer"]),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.expected_value} {self.currency})"

    @property
    def weighted_value(self) -> Decimal:
        """Estimated value weighted by stage win probability."""
        return (self.expected_value * Decimal(self.probability_percent) / Decimal(100)).quantize(
            Decimal("0.0001")
        )


class InteractionType(models.TextChoices):
    NOTE = "note", _("Internal Note")
    CALL = "call", _("Phone Call")
    EMAIL = "email", _("Email Exchange")
    MEETING = "meeting", _("Meeting / Demo")


class Interaction(TenantModel):
    """Chronological touchpoint or communication logged against CRM records."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    type = models.CharField(
        _("Activity Type"),
        max_length=20,
        choices=InteractionType.choices,
        default=InteractionType.NOTE,
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="crm_interactions",
        verbose_name=_("Customer"),
    )
    lead = models.ForeignKey(
        Lead,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="crm_interactions",
        verbose_name=_("Lead"),
    )
    opportunity = models.ForeignKey(
        Opportunity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="crm_interactions",
        verbose_name=_("Opportunity"),
    )
    summary = models.CharField(_("Summary / Subject"), max_length=255)
    details = models.TextField(_("Details / Body"), blank=True)
    occurred_at = models.DateTimeField(_("Occurred At"), default=timezone.now)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="logged_crm_interactions",
        verbose_name=_("Logged By"),
    )

    class Meta:
        verbose_name = _("Interaction")
        verbose_name_plural = _("Interactions")
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["organization", "customer", "-occurred_at"]),
            models.Index(fields=["organization", "lead", "-occurred_at"]),
            models.Index(fields=["organization", "opportunity", "-occurred_at"]),
        ]

    def __str__(self) -> str:
        return f"[{self.get_type_display()}] {self.summary}"


class TaskPriority(models.TextChoices):
    LOW = "low", _("Low")
    MEDIUM = "medium", _("Medium")
    HIGH = "high", _("High")
    URGENT = "urgent", _("Urgent")


class TaskStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    IN_PROGRESS = "in_progress", _("In Progress")
    COMPLETED = "completed", _("Completed")
    CANCELLED = "cancelled", _("Cancelled")


class CrmTask(TenantModel):
    """Actionable to-do item or scheduled follow-up for sales reps."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    title = models.CharField(_("Task Title"), max_length=255)
    description = models.TextField(_("Description"), blank=True)
    due_date = models.DateField(_("Due Date"), null=True, blank=True)
    priority = models.CharField(
        _("Priority"),
        max_length=20,
        choices=TaskPriority.choices,
        default=TaskPriority.MEDIUM,
    )
    status = models.CharField(
        _("Status"),
        max_length=20,
        choices=TaskStatus.choices,
        default=TaskStatus.PENDING,
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="crm_assigned_tasks",
        verbose_name=_("Assigned To"),
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="crm_tasks",
        verbose_name=_("Customer"),
    )
    lead = models.ForeignKey(
        Lead,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="crm_tasks",
        verbose_name=_("Lead"),
    )
    opportunity = models.ForeignKey(
        Opportunity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="crm_tasks",
        verbose_name=_("Opportunity"),
    )
    completed_at = models.DateTimeField(_("Completed At"), null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="completed_crm_tasks",
        verbose_name=_("Completed By"),
    )

    class Meta:
        verbose_name = _("CRM Task")
        verbose_name_plural = _("CRM Tasks")
        ordering = ["status", "due_date", "-created_at"]
        indexes = [
            models.Index(fields=["organization", "status", "due_date"]),
            models.Index(fields=["organization", "assigned_to", "status"]),
            models.Index(fields=["organization", "customer", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.get_status_display()})"
