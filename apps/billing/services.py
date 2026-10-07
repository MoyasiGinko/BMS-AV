"""Billing services: Plan seeding, subscription lifecycle, usage counters, and entitlement checking."""

from __future__ import annotations

import datetime
import logging
import uuid
from collections.abc import Callable
from decimal import Decimal
from functools import wraps
from typing import Any

from django.apps import apps
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.billing.events import (
    SubscriptionCanceledEvent,
    SubscriptionChangedEvent,
    SubscriptionCreatedEvent,
    SubscriptionPaymentFailedEvent,
    SubscriptionReadOnlyEvent,
    SubscriptionRenewedEvent,
)
from apps.billing.gateway import GatewayWebhookEvent, get_payment_gateway
from apps.billing.models import (
    Module,
    Plan,
    PlanModule,
    ProcessedWebhookEvent,
    Subscription,
    SubscriptionInvoice,
    UsageCounter,
)
from apps.billing.registry import registry
from apps.core.events import publish
from apps.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default Plan Definitions
# ---------------------------------------------------------------------------

DEFAULT_TIERS: list[dict[str, Any]] = [
    {
        "name": "Starter",
        "slug": "starter",
        "description": "Essential operations for single-location retail and service businesses.",
        "price_monthly": Decimal("29.00"),
        "price_yearly": Decimal("290.00"),
        "trial_days": 14,
        "max_users": 3,
        "max_branches": 1,
        "max_warehouses": 1,
        "sort_order": 1,
        "modules": ["billing", "settings", "catalog", "customers", "sales", "pos"],
    },
    {
        "name": "Growth",
        "slug": "growth",
        "description": "Growing multi-branch operations with inventory management and purchasing.",
        "price_monthly": Decimal("79.00"),
        "price_yearly": Decimal("790.00"),
        "trial_days": 14,
        "max_users": 10,
        "max_branches": 3,
        "max_warehouses": 3,
        "sort_order": 2,
        "modules": [
            "billing",
            "settings",
            "catalog",
            "customers",
            "sales",
            "pos",
            "inventory",
            "purchasing",
            "reports",
            "crm",
        ],
    },
    {
        "name": "Business",
        "slug": "business",
        "description": "Comprehensive ERP suite with general ledger accounting, HR, and payroll.",
        "price_monthly": Decimal("199.00"),
        "price_yearly": Decimal("1990.00"),
        "trial_days": 14,
        "max_users": 30,
        "max_branches": 10,
        "max_warehouses": 10,
        "sort_order": 3,
        "modules": [
            "billing",
            "settings",
            "catalog",
            "customers",
            "sales",
            "pos",
            "inventory",
            "purchasing",
            "reports",
            "crm",
            "accounting",
            "hr",
            "payroll",
            "automation",
        ],
    },
    {
        "name": "Enterprise",
        "slug": "enterprise",
        "description": "Unlimited scale, advanced integrations, API access, and AI Assistant copilot.",
        "price_monthly": Decimal("499.00"),
        "price_yearly": Decimal("4990.00"),
        "trial_days": 30,
        "max_users": -1,
        "max_branches": -1,
        "max_warehouses": -1,
        "sort_order": 4,
        "modules": [
            "billing",
            "settings",
            "catalog",
            "customers",
            "sales",
            "pos",
            "inventory",
            "purchasing",
            "reports",
            "crm",
            "accounting",
            "hr",
            "payroll",
            "automation",
            "integrations",
            "ai",
        ],
    },
]


@transaction.atomic
def seed_default_plans() -> dict[str, Plan]:
    """Seed modules from ModuleRegistry and initialize default subscription tiers."""
    # 1. Sync modules
    modules_by_key: dict[str, Module] = {}
    for mod_def in registry.all():
        mod, _ = Module.objects.update_or_create(
            key=mod_def.key,
            defaults={
                "name": mod_def.name,
                "description": mod_def.description,
                "icon": mod_def.icon,
                "sort_order": mod_def.sort_order,
            },
        )
        modules_by_key[mod.key] = mod

    # 2. Sync plans and plan-module matrix
    created_plans: dict[str, Plan] = {}
    for tier in DEFAULT_TIERS:
        plan, _ = Plan.objects.update_or_create(
            slug=tier["slug"],
            defaults={
                "name": tier["name"],
                "description": tier["description"],
                "price_monthly": tier["price_monthly"],
                "price_yearly": tier["price_yearly"],
                "trial_days": tier["trial_days"],
                "max_users": tier["max_users"],
                "max_branches": tier["max_branches"],
                "max_warehouses": tier["max_warehouses"],
                "sort_order": tier["sort_order"],
                "is_active": True,
            },
        )
        created_plans[plan.slug] = plan

        allowed_keys = set(tier["modules"])
        for key, module_obj in modules_by_key.items():
            included = key in allowed_keys
            PlanModule.objects.update_or_create(
                plan=plan,
                module=module_obj,
                defaults={"included": included},
            )

    logger.info("Successfully seeded %d billing plans and module matrix.", len(created_plans))
    return created_plans


# ---------------------------------------------------------------------------
# Subscription Management
# ---------------------------------------------------------------------------


@transaction.atomic
def create_subscription(
    *,
    organization: Any,
    plan: Plan | str,
    actor: Any = None,
    interval: str = "monthly",
    trial_days: int | None = None,
) -> Subscription:
    """Create or enroll a tenant organization into a subscription plan."""
    if isinstance(plan, str):
        plan = Plan.objects.get(slug=plan)

    now = timezone.now()
    eff_trial_days = plan.trial_days if trial_days is None else trial_days

    if eff_trial_days > 0:
        status = Subscription.STATUS_TRIALING
        trial_start = now
        trial_end = now + datetime.timedelta(days=eff_trial_days)
        period_start = now
        period_end = trial_end
    else:
        status = Subscription.STATUS_ACTIVE
        trial_start = None
        trial_end = None
        period_start = now
        days = 30 if interval == "monthly" else 365
        period_end = now + datetime.timedelta(days=days)

    subscription, _ = Subscription.all_tenants.select_for_update().update_or_create(
        organization=organization,
        defaults={
            "plan": plan,
            "status": status,
            "billing_interval": interval,
            "trial_start": trial_start,
            "trial_end": trial_end,
            "current_period_start": period_start,
            "current_period_end": period_end,
            "renews_at": period_end,
            "cancel_at_period_end": False,
            "canceled_at": None,
        },
    )

    publish(
        SubscriptionCreatedEvent(
            organization_id=getattr(organization, "pk", getattr(organization, "id", None)),
            actor_id=getattr(actor, "pk", getattr(actor, "id", None)),
            subscription_id=subscription.pk,
            plan_slug=plan.slug,
            status=status,
            billing_interval=interval,
        )
    )

    return subscription


@transaction.atomic
def change_subscription_plan(
    *,
    subscription: Subscription,
    new_plan: Plan | str,
    interval: str | None = None,
    actor: Any = None,
) -> Subscription:
    """Change the subscription plan for an organization."""
    if isinstance(new_plan, str):
        new_plan = Plan.objects.get(slug=new_plan)

    sub = Subscription.all_tenants.select_for_update().get(pk=subscription.pk)
    old_plan_slug = sub.plan.slug
    sub.plan = new_plan
    update_fields = ["plan", "cancel_at_period_end", "updated_at"]
    if interval:
        sub.billing_interval = interval
        update_fields.append("billing_interval")
    sub.cancel_at_period_end = False

    if sub.gateway_subscription_id:
        gw = get_payment_gateway()
        gw.update_subscription(
            gateway_subscription_id=sub.gateway_subscription_id,
            new_plan_slug=new_plan.slug,
            interval=sub.billing_interval,
        )

    sub.save(update_fields=update_fields)

    publish(
        SubscriptionChangedEvent(
            organization_id=getattr(sub.organization, "pk", getattr(sub.organization, "id", None)),
            actor_id=getattr(actor, "pk", getattr(actor, "id", None)),
            subscription_id=sub.pk,
            old_plan_slug=old_plan_slug,
            new_plan_slug=new_plan.slug,
        )
    )

    return sub


@transaction.atomic
def cancel_subscription(
    *,
    subscription: Subscription,
    actor: Any = None,
    immediately: bool = False,
) -> Subscription:
    """Cancel a subscription immediately or schedule cancellation for period end."""
    sub = Subscription.all_tenants.select_for_update().get(pk=subscription.pk)

    if immediately:
        sub.status = Subscription.STATUS_CANCELED
        sub.canceled_at = timezone.now()
        sub.cancel_at_period_end = False
        sub.save(update_fields=["status", "canceled_at", "cancel_at_period_end", "updated_at"])
    else:
        sub.cancel_at_period_end = True
        sub.save(update_fields=["cancel_at_period_end", "updated_at"])

    publish(
        SubscriptionCanceledEvent(
            organization_id=getattr(sub.organization, "pk", getattr(sub.organization, "id", None)),
            actor_id=getattr(actor, "pk", getattr(actor, "id", None)),
            subscription_id=sub.pk,
            plan_slug=sub.plan.slug,
            immediate=immediately,
        )
    )

    return sub


@transaction.atomic
def transition_subscription_status(
    *,
    subscription: Subscription,
    new_status: str,
    actor: Any = None,
    grace_period_days: int = 7,
) -> Subscription:
    """Transition subscription through its lifecycle state machine."""
    sub = Subscription.all_tenants.select_for_update().get(pk=subscription.pk)
    old_status = sub.status

    if old_status != new_status:
        allowed = Subscription.ALLOWED_TRANSITIONS.get(old_status, [])
        if new_status not in allowed:
            raise ValidationError(
                _("Invalid subscription transition from %(old)s to %(new)s.")
                % {"old": old_status, "new": new_status}
            )

    sub.status = new_status
    update_fields = ["status", "updated_at"]

    if new_status == Subscription.STATUS_PAST_DUE:
        if sub.grace_period_end is None or sub.grace_period_end < timezone.now():
            sub.grace_period_end = timezone.now() + datetime.timedelta(days=grace_period_days)
            update_fields.append("grace_period_end")
        publish(
            SubscriptionPaymentFailedEvent(
                organization_id=getattr(sub.organization, "pk", getattr(sub.organization, "id", None)),
                actor_id=getattr(actor, "pk", getattr(actor, "id", None)),
                subscription_id=sub.pk,
                grace_period_end=sub.grace_period_end.isoformat() if sub.grace_period_end else None,
            )
        )
    elif new_status == Subscription.STATUS_ACTIVE:
        if sub.grace_period_end is not None:
            sub.grace_period_end = None
            update_fields.append("grace_period_end")
    elif new_status == Subscription.STATUS_UNPAID:
        publish(
            SubscriptionReadOnlyEvent(
                organization_id=getattr(sub.organization, "pk", getattr(sub.organization, "id", None)),
                actor_id=getattr(actor, "pk", getattr(actor, "id", None)),
                subscription_id=sub.pk,
            )
        )

    sub.save(update_fields=update_fields)
    return sub


@transaction.atomic
def create_subscription_invoice(
    *,
    organization: Any,
    amount: Decimal,
    period_start: datetime.datetime,
    period_end: datetime.datetime,
    status: str = SubscriptionInvoice.STATUS_PAID,
    currency: str = "USD",
    billing_reason: str = "subscription_cycle",
    invoice_number: str | None = None,
    gateway_invoice_id: str = "",
    hosted_invoice_url: str = "",
    pdf_url: str = "",
    paid_at: datetime.datetime | None = None,
) -> SubscriptionInvoice:
    """Create a subscription invoice record for an organization."""
    if not invoice_number:
        seq_num = f"{timezone.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
        invoice_number = f"SUB-{seq_num}"

    effective_paid_at = paid_at or (timezone.now() if status == SubscriptionInvoice.STATUS_PAID else None)

    invoice = SubscriptionInvoice.all_tenants.create(
        organization=organization,
        invoice_number=invoice_number,
        amount=amount,
        currency=currency,
        status=status,
        billing_reason=billing_reason,
        period_start=period_start,
        period_end=period_end,
        paid_at=effective_paid_at,
        hosted_invoice_url=hosted_invoice_url,
        pdf_url=pdf_url,
        gateway_invoice_id=gateway_invoice_id,
    )
    return invoice


@transaction.atomic
def process_gateway_webhook_event(event: GatewayWebhookEvent) -> dict[str, Any]:
    """Process an incoming gateway webhook idempotently."""
    if ProcessedWebhookEvent.objects.filter(event_id=event.event_id).exists():
        logger.info("Webhook event %s already processed. Skipping duplicate.", event.event_id)
        return {"status": "duplicate_ignored", "event_id": event.event_id}

    ProcessedWebhookEvent.objects.create(
        event_id=event.event_id,
        event_type=event.event_type,
        payload=event.data,
    )

    data = event.data
    customer_id = data.get("customer_id") or data.get("customer")
    sub_id = data.get("subscription_id") or data.get("subscription")

    # Find matching subscription
    sub: Subscription | None = None
    if sub_id:
        sub = Subscription.all_tenants.select_for_update().filter(gateway_subscription_id=sub_id).first()
    if sub is None and customer_id:
        sub = Subscription.all_tenants.select_for_update().filter(customer_id=customer_id).first()

    now = timezone.now()

    if event.event_type in ("invoice.paid", "payment.succeeded"):
        if sub:
            raw_amount = data.get("amount", data.get("amount_paid", 0))
            amount = Decimal(str(raw_amount)) if not isinstance(raw_amount, Decimal) else raw_amount
            if isinstance(raw_amount, int) and raw_amount >= 100:
                amount = Decimal(str(raw_amount)) / Decimal("100")

            currency = data.get("currency", "USD").upper()
            period_start = sub.current_period_end or now
            interval_days = 365 if sub.billing_interval == "yearly" else 30
            period_end = period_start + datetime.timedelta(days=interval_days)

            create_subscription_invoice(
                organization=sub.organization,
                amount=amount,
                currency=currency,
                period_start=period_start,
                period_end=period_end,
                status=SubscriptionInvoice.STATUS_PAID,
                gateway_invoice_id=data.get("invoice_id", data.get("id", "")),
                hosted_invoice_url=data.get("hosted_invoice_url", ""),
                pdf_url=data.get("invoice_pdf", ""),
                paid_at=now,
            )

            sub.status = Subscription.STATUS_ACTIVE
            sub.current_period_start = period_start
            sub.current_period_end = period_end
            sub.renews_at = period_end
            sub.grace_period_end = None
            sub.save(
                update_fields=[
                    "status",
                    "current_period_start",
                    "current_period_end",
                    "renews_at",
                    "grace_period_end",
                    "updated_at",
                ]
            )

            publish(
                SubscriptionRenewedEvent(
                    organization_id=sub.organization.pk,
                    subscription_id=sub.pk,
                    new_period_end=period_end.isoformat(),
                )
            )

    elif event.event_type in ("invoice.payment_failed", "payment.failed"):
        if sub:
            raw_amount = data.get("amount", 0)
            amount = Decimal(str(raw_amount)) if not isinstance(raw_amount, Decimal) else raw_amount
            if isinstance(raw_amount, int) and raw_amount >= 100:
                amount = Decimal(str(raw_amount)) / Decimal("100")

            period_start = sub.current_period_start or now
            period_end = sub.current_period_end or now

            create_subscription_invoice(
                organization=sub.organization,
                amount=amount,
                currency=data.get("currency", "USD").upper(),
                period_start=period_start,
                period_end=period_end,
                status=SubscriptionInvoice.STATUS_OPEN,
                gateway_invoice_id=data.get("invoice_id", data.get("id", "")),
            )

            transition_subscription_status(
                subscription=sub,
                new_status=Subscription.STATUS_PAST_DUE,
            )

    elif event.event_type in ("customer.subscription.deleted", "subscription.canceled") and sub:
        sub.status = Subscription.STATUS_CANCELED
        sub.canceled_at = now
        sub.save(update_fields=["status", "canceled_at", "updated_at"])
        publish(
            SubscriptionCanceledEvent(
                organization_id=sub.organization.pk,
                subscription_id=sub.pk,
                plan_slug=sub.plan.slug,
                immediate=True,
            )
        )

    return {"status": "processed", "event_id": event.event_id, "event_type": event.event_type}


@transaction.atomic
def check_subscription_grace_periods() -> int:
    """Inspect past_due subscriptions and transition expired grace periods to read-only (unpaid)."""
    now = timezone.now()
    expired_subs = Subscription.all_tenants.select_for_update().filter(
        status=Subscription.STATUS_PAST_DUE, grace_period_end__lt=now
    )
    count = 0
    for sub in expired_subs:
        sub.status = Subscription.STATUS_UNPAID
        sub.save(update_fields=["status", "updated_at"])
        publish(
            SubscriptionReadOnlyEvent(
                organization_id=sub.organization.pk,
                subscription_id=sub.pk,
            )
        )
        count += 1
    return count


# ---------------------------------------------------------------------------
# Usage Metering
# ---------------------------------------------------------------------------


@transaction.atomic
def increment_usage(
    *,
    organization_id: int,
    metric: str,
    amount: int = 1,
    for_date: datetime.date | None = None,
) -> UsageCounter:
    """Increment metric usage counter atomically within the calendar month."""
    target_date = for_date or timezone.now().date()
    period_start = target_date.replace(day=1)

    # Next month computation
    next_month = (period_start.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    period_end = next_month - datetime.timedelta(days=1)

    counter, _ = UsageCounter.all_tenants.select_for_update().get_or_create(
        organization_id=organization_id,
        metric=metric,
        period_start=period_start,
        defaults={
            "period_end": period_end,
            "value": 0,
        },
    )

    counter.value += amount
    counter.save(update_fields=["value", "updated_at"])
    return counter


# ---------------------------------------------------------------------------
# Entitlement & Quota Verification
# ---------------------------------------------------------------------------


def check_organization_feature_entitlement(organization: Any, feature_code: str) -> bool | None:
    """Entitlement engine callback (Layer 1).

    Returns:
        True: if feature/module is permitted under active plan.
        False: if forbidden or subscription is expired/missing.
        None: if no opinion (falls back to next checker or default).
    """
    if organization is None:
        return False

    module_key = feature_code.split(".", 1)[0] if "." in feature_code else feature_code
    mod_def = registry.get(module_key)

    # Core platform modules are universally accessible
    if mod_def and mod_def.is_core:
        return True

    subscription = Subscription.all_tenants.filter(organization=organization).select_related("plan").first()

    if subscription is None:
        return None

    if not subscription.is_active_or_trialing:
        return False

    # Check PlanModule inclusion
    return PlanModule.objects.filter(
        plan=subscription.plan,
        module__key=module_key,
        included=True,
    ).exists()


def require_task_feature(feature_code: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator for Celery background tasks to verify tenant feature entitlement.

    If organization is not entitled, execution is skipped and logged.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            org_id = kwargs.get("organization_id")
            if org_id is None and args and isinstance(args[0], int):
                org_id = args[0]

            if org_id is not None:
                org_model = apps.get_model("tenancy", "Organization")
                org = org_model.objects.filter(pk=org_id).first()
                if org and not check_organization_feature_entitlement(org, feature_code):
                    logger.warning(
                        "Task '%s' skipped: organization %s is not entitled to '%s'.",
                        fn.__name__,
                        org_id,
                        feature_code,
                    )
                    return None
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def provision_billing_subscription(ctx: Any) -> None:
    """Provision initial subscription and module access for newly created organization."""
    plan_slug = ctx.extra_data.get("plan_slug")
    if not plan_slug:
        return

    if not Plan.objects.exists():
        seed_default_plans()

    create_subscription(
        organization=ctx.organization,
        plan=plan_slug,
        actor=ctx.owner,
        interval="monthly",
    )
