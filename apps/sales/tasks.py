"""Celery background and beat periodic tasks for Sales, Recurring Invoices, and Payment Reminders."""

from __future__ import annotations

import logging

from celery import shared_task
from django.contrib.auth import get_user_model

from apps.sales import services
from apps.sales.models import RecurringInvoiceProfile

logger = logging.getLogger(__name__)


@shared_task(name="sales.process_due_recurring_invoices")
def process_due_recurring_invoices_task() -> str:
    """Periodic beat task: find all active recurring invoice profiles that are due and generate invoices."""
    try:
        results = services.generate_due_recurring_invoices()
        count = len(results.get("generated", [])) if isinstance(results, dict) else len(results)
        msg = f"Recurring invoices processed: {count} invoices generated."
        logger.info(msg)
        return msg
    except Exception as exc:
        logger.exception("process_due_recurring_invoices_task failed: %s", exc)
        raise


@shared_task(name="sales.dispatch_due_payment_reminders")
def dispatch_payment_reminders_task() -> str:
    """Periodic beat task: find unpaid posted invoices matching active reminder rules and dispatch notices."""
    try:
        results = services.process_due_payment_reminders()
        count = len(results.get("sent", [])) if isinstance(results, dict) else len(results)
        msg = f"Payment reminders processed: {count} notices dispatched."
        logger.info(msg)
        return msg
    except Exception as exc:
        logger.exception("dispatch_payment_reminders_task failed: %s", exc)
        raise


@shared_task(name="sales.generate_single_recurring_invoice")
def generate_single_recurring_invoice_task(profile_id: int, actor_id: int | None = None) -> str:
    """Async task: generate an invoice for a specific recurring profile on demand."""
    profile = RecurringInvoiceProfile.all_tenants.filter(pk=profile_id).first()
    if not profile:
        msg = f"Recurring profile {profile_id} not found."
        logger.warning(msg)
        return msg

    User = get_user_model()
    actor = User.objects.filter(pk=actor_id).first() if actor_id else None

    invoice = services.generate_single_recurring_invoice(profile=profile, actor=actor)
    return f"Generated invoice {invoice.invoice_number} from recurring profile {profile.title}."
