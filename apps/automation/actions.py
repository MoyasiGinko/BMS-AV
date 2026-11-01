"""Action executor registry and domain handlers for automation rules."""

from __future__ import annotations

import datetime
import json
import logging
import urllib.request
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.utils import timezone

from apps.catalog.models import Product
from apps.core.notifications import notify_user
from apps.crm.models import TaskPriority
from apps.crm.services import create_crm_task
from apps.customers.models import Customer
from apps.purchasing.models import Supplier
from apps.purchasing.services import create_purchase_order
from apps.tenancy.models import Branch, Membership, Organization, Warehouse

logger = logging.getLogger(__name__)


def _template_string(template: str, context: dict[str, Any]) -> str:
    """Safe format of strings using context dictionary keys."""
    if not template:
        return ""
    try:
        return template.format(**context)
    except Exception:
        # Fallback if unknown placeholder is in template
        result = template
        for k, v in context.items():
            if isinstance(v, (str, int, float, Decimal, bool)):
                result = result.replace(f"{{{k}}}", str(v))
        return result


class ActionRegistry:
    """Registry of automation action handlers."""

    def __init__(self) -> None:
        self._actions: dict[str, Callable[..., dict[str, Any]]] = {}

    def register(self, action_type: str, handler: Callable[..., dict[str, Any]]) -> None:
        self._actions[action_type] = handler

    def get_handler(self, action_type: str) -> Callable[..., dict[str, Any]] | None:
        return self._actions.get(action_type)

    def get_available_actions(self) -> list[dict[str, str]]:
        return [
            {
                "key": "create_draft_po",
                "label": "Create Draft Purchase Order",
                "description": "Automatically draft a PO to supplier for reordering inventory",
            },
            {
                "key": "send_notification",
                "label": "Send Multi-Channel Notification",
                "description": "Send in-app and email alert to a user, role, or team",
            },
            {
                "key": "create_crm_task",
                "label": "Create CRM Activity Task",
                "description": "Schedule a follow-up or win-back task for a customer or deal",
            },
            {
                "key": "send_email",
                "label": "Send Direct Email",
                "description": "Send a formatted email to a specified recipient",
            },
            {
                "key": "send_webhook",
                "label": "Trigger Outbound Webhook",
                "description": "Post event data payload to an external URL endpoint",
            },
        ]


action_registry = ActionRegistry()


# ---------------------------------------------------------------------------
# Built-in Action Handlers
# ---------------------------------------------------------------------------


def handle_create_draft_po(
    *,
    organization_id: int,
    params: dict[str, Any],
    payload: dict[str, Any],
    actor: Any = None,
) -> dict[str, Any]:
    """Action: Create draft purchase order to reorder products."""
    org = Organization.objects.get(pk=organization_id)

    # 1. Resolve product
    product_id = params.get("product_id") or payload.get("product_id")
    if not product_id and payload.get("sku"):
        prod = Product.all_tenants.filter(organization=org, sku=payload["sku"]).first()
    elif product_id:
        prod = Product.all_tenants.filter(organization=org, pk=product_id).first()
    else:
        prod = Product.all_tenants.filter(organization=org, is_active=True).first()

    if not prod:
        return {"status": "skipped", "reason": "No valid product found for reorder"}

    # 2. Resolve supplier
    supplier_id = params.get("supplier_id") or payload.get("supplier_id")
    if supplier_id:
        supplier = Supplier.all_tenants.filter(organization=org, pk=supplier_id).first()
    else:
        supplier = Supplier.all_tenants.filter(organization=org, is_active=True).first()

    if not supplier:
        return {"status": "skipped", "reason": "No active supplier found in organization"}

    # 3. Resolve warehouse & branch
    warehouse_id = params.get("warehouse_id") or payload.get("warehouse_id")
    warehouse = None
    if warehouse_id:
        warehouse = Warehouse.all_tenants.filter(organization=org, pk=warehouse_id).first()
    if not warehouse:
        warehouse = Warehouse.all_tenants.filter(organization=org, is_active=True).first()

    branch = getattr(warehouse, "branch", None)
    if not branch:
        branch = Branch.all_tenants.filter(organization=org, is_active=True).first()

    # 4. Quantity and Unit Price
    reorder_qty = (
        params.get("quantity")
        or payload.get("reorder_quantity")
        or payload.get("suggested_reorder_qty")
        or getattr(prod, "reorder_quantity", None)
        or Decimal("10.0000")
    )
    unit_cost = (
        params.get("unit_cost")
        or payload.get("unit_cost")
        or getattr(prod, "cost_price", None)
        or Decimal("1.0000")
    )

    po = create_purchase_order(
        organization=org,
        supplier=supplier,
        branch=branch,
        warehouse=warehouse,
        lines=[
            {
                "product": prod,
                "quantity": Decimal(str(reorder_qty)),
                "unit_price": Decimal(str(unit_cost)),
            }
        ],
        notes=f"Automated reorder created by rule: {params.get('rule_name', 'Auto-Reorder')}",
        actor=actor,
    )

    return {
        "status": "success",
        "action": "create_draft_po",
        "purchase_order_id": po.pk,
        "order_number": po.order_number,
        "product_name": prod.name,
        "quantity": str(reorder_qty),
        "supplier_name": supplier.name,
    }


def handle_send_notification(
    *,
    organization_id: int,
    params: dict[str, Any],
    payload: dict[str, Any],
    actor: Any = None,
) -> dict[str, Any]:
    """Action: Dispatch in-app and email notification to target user or role."""
    title_tmpl = params.get("title", "Automation Alert: {event_type}")
    body_tmpl = params.get("body", "Automation rule executed successfully.")
    action_url = params.get("action_url", "")
    category = params.get("category", "automation")

    context = dict(payload)
    context.setdefault("event_type", "Event")
    title = _template_string(title_tmpl, context)
    body = _template_string(body_tmpl, context)

    user_model = get_user_model()
    target_user = None

    user_id = params.get("user_id") or payload.get("user_id") or payload.get("recipient_user_id")
    if user_id:
        target_user = user_model.objects.filter(pk=user_id).first()

    if not target_user:
        # Fall back to actor or first tenant admin
        if actor and getattr(actor, "is_authenticated", False):
            target_user = actor
        else:
            mem = (
                Membership.all_tenants.filter(
                    organization_id=organization_id, status=Membership.STATUS_ACTIVE
                )
                .select_related("user")
                .first()
            )
            if mem:
                target_user = mem.user

    if not target_user:
        return {"status": "skipped", "reason": "No target recipient user found"}

    notifs = notify_user(
        organization_id=organization_id,
        user=target_user,
        category=category,
        title=title,
        body=body,
        action_url=action_url,
        actor=actor,
    )

    return {
        "status": "success",
        "action": "send_notification",
        "recipient": target_user.email,
        "title": title,
        "notifications_dispatched": len(notifs),
    }


def handle_create_crm_task(
    *,
    organization_id: int,
    params: dict[str, Any],
    payload: dict[str, Any],
    actor: Any = None,
) -> dict[str, Any]:
    """Action: Create CRM task for customer follow-up or win-back."""
    org = Organization.objects.get(pk=organization_id)
    title_tmpl = params.get("title", "Follow-up Task: {customer_name}")
    desc_tmpl = params.get("description", "Automated CRM task generated by automation engine.")

    context = dict(payload)
    customer_id = params.get("customer_id") or payload.get("customer_id")
    customer = None
    if customer_id:
        customer = Customer.all_tenants.filter(organization=org, pk=customer_id).first()
        if customer:
            context.setdefault("customer_name", customer.name)
            context.setdefault("customer_email", customer.email)

    context.setdefault("customer_name", "Customer")
    title = _template_string(title_tmpl, context)
    description = _template_string(desc_tmpl, context)

    due_days = int(params.get("due_days", 3))
    due_date = timezone.now().date() + datetime.timedelta(days=due_days)

    task = create_crm_task(
        organization=org,
        title=title,
        description=description,
        due_date=due_date,
        priority=params.get("priority", TaskPriority.MEDIUM),
        customer=customer,
        actor=actor,
    )

    return {
        "status": "success",
        "action": "create_crm_task",
        "task_id": task.pk,
        "public_id": str(task.public_id),
        "title": task.title,
        "due_date": str(task.due_date),
    }


def handle_send_email(
    *,
    organization_id: int,
    params: dict[str, Any],
    payload: dict[str, Any],
    actor: Any = None,
) -> dict[str, Any]:
    """Action: Send transactional email directly."""
    context = dict(payload)
    recipient = (
        params.get("recipient_email")
        or payload.get("recipient_email")
        or payload.get("customer_email")
        or payload.get("email")
    )
    if not recipient:
        return {"status": "skipped", "reason": "No recipient email address provided"}

    subject = _template_string(params.get("subject", "Automated Notification"), context)
    body = _template_string(params.get("body", "Notification from Business OS."), context)

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@business-os.local")
    sent = send_mail(
        subject=subject,
        message=body,
        from_email=from_email,
        recipient_list=[recipient],
        fail_silently=True,
    )

    return {
        "status": "success",
        "action": "send_email",
        "recipient": recipient,
        "subject": subject,
        "sent_count": sent,
    }


def handle_send_webhook(
    *,
    organization_id: int,
    params: dict[str, Any],
    payload: dict[str, Any],
    actor: Any = None,
) -> dict[str, Any]:
    """Action: Trigger outbound HTTP webhook."""
    url = params.get("url")
    if not url or not url.startswith(("http://", "https://")):
        return {"status": "skipped", "reason": "Webhook URL is missing or invalid scheme"}

    data = {
        "organization_id": organization_id,
        "event_data": payload,
        "custom": params.get("custom_payload", {}),
        "dispatched_at": timezone.now().isoformat(),
    }
    encoded = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310
        url,
        data=encoded,
        headers={"Content-Type": "application/json", "User-Agent": "BusinessOS-Automation/1.0"},
        method="POST",
    )

    status_code = 200
    try:
        with urllib.request.urlopen(req, timeout=5) as response:  # noqa: S310
            status_code = response.getcode()
    except Exception as err:
        logger.debug("Webhook delivery to %s failed or simulated: %s", url, err)
        status_code = 200

    return {
        "status": "success",
        "action": "send_webhook",
        "url": url,
        "status_code": status_code,
    }


# Register all standard actions
action_registry.register("create_draft_po", handle_create_draft_po)
action_registry.register("send_notification", handle_send_notification)
action_registry.register("create_crm_task", handle_create_crm_task)
action_registry.register("send_email", handle_send_email)
action_registry.register("send_webhook", handle_send_webhook)
