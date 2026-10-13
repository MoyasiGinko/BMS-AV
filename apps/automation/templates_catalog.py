"""Template catalog of pre-built automation rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from apps.automation.models import TriggerType


@dataclass(frozen=True)
class AutomationTemplateDefinition:
    key: str
    name: str
    category: str
    description: str
    icon: str
    trigger_type: str
    trigger_event: str
    trigger_config: dict[str, Any] = field(default_factory=dict)
    conditions: list[dict[str, Any]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "icon": self.icon,
            "trigger_type": self.trigger_type,
            "trigger_event": self.trigger_event,
            "trigger_config": self.trigger_config,
            "conditions": self.conditions,
            "actions": self.actions,
        }


TEMPLATES: list[AutomationTemplateDefinition] = [
    AutomationTemplateDefinition(
        key="low_stock_reorder_draft_po",
        name="Low Stock Auto-Reorder (Draft PO)",
        category="Inventory & Purchasing",
        description=(
            "Automatically drafts a purchase order to your primary supplier and notifies "
            "the procurement team when inventory drops to or below safety stock."
        ),
        icon="archive-box-arrow-down",
        trigger_type=TriggerType.EVENT,
        trigger_event="stock.low",
        conditions=[
            {
                "field": "quantity_on_hand",
                "operator": "less_than_or_equal",
                "value": 10,
            }
        ],
        actions=[
            {
                "action_type": "create_draft_po",
                "params": {
                    "quantity": 25,
                    "rule_name": "Low Stock Auto-Reorder",
                },
            },
            {
                "action_type": "send_notification",
                "params": {
                    "title": "Low Stock Reorder: {sku}",
                    "body": (
                        "Stock for item {sku} dropped to {quantity_on_hand}. "
                        "A draft PO has been generated for review."
                    ),
                    "category": "inventory",
                },
            },
        ],
    ),
    AutomationTemplateDefinition(
        key="overdue_invoice_reminder",
        name="Overdue Invoice Follow-Up Reminder",
        category="Sales & Invoicing",
        description=(
            "Dispatches multi-channel alerts and sends an email reminder to customers "
            "when unpaid invoices pass their due date."
        ),
        icon="banknotes",
        trigger_type=TriggerType.EVENT,
        trigger_event="invoice.overdue",
        conditions=[
            {
                "field": "status",
                "operator": "equals",
                "value": "overdue",
            }
        ],
        actions=[
            {
                "action_type": "send_notification",
                "params": {
                    "title": "Invoice {invoice_number} Overdue",
                    "body": (
                        "Invoice {invoice_number} for customer {customer_name} is overdue. "
                        "Outstanding balance: ${total_amount}."
                    ),
                    "category": "billing",
                },
            },
            {
                "action_type": "send_email",
                "params": {
                    "subject": "Payment Reminder: Invoice {invoice_number}",
                    "body": (
                        "Dear {customer_name},\n\n"
                        "This is a friendly reminder that invoice {invoice_number} for ${total_amount} "
                        "was due on {due_date}. Please submit payment at your earliest convenience.\n\n"
                        "Thank you for your business."
                    ),
                },
            },
        ],
    ),
    AutomationTemplateDefinition(
        key="customer_win_back",
        name="Inactive Customer Win-Back Campaign",
        category="CRM & Customers",
        description=(
            "Creates an urgent CRM activity task for account executives when an existing customer "
            "has placed no new orders for 60+ days."
        ),
        icon="user-group",
        trigger_type=TriggerType.EVENT,
        trigger_event="customer.inactive",
        conditions=[
            {
                "field": "days_since_last_order",
                "operator": "greater_than_or_equal",
                "value": 60,
            }
        ],
        actions=[
            {
                "action_type": "create_crm_task",
                "params": {
                    "title": "Win-Back Outreach: {customer_name}",
                    "description": (
                        "Customer has had no purchase activity for {days_since_last_order} days. "
                        "Reach out with check-in or promotion."
                    ),
                    "priority": "high",
                    "due_days": 3,
                },
            },
            {
                "action_type": "send_notification",
                "params": {
                    "title": "Inactive Customer: {customer_name}",
                    "body": "A win-back task has been scheduled for {customer_name}.",
                    "category": "crm",
                },
            },
        ],
    ),
    AutomationTemplateDefinition(
        key="high_value_deal_alert",
        name="High-Value Opportunity Alert",
        category="Sales & CRM",
        description=(
            "Alerts management when a high-value sales deal (> $10,000) advances to "
            "late proposal or negotiation stages."
        ),
        icon="sparkles",
        trigger_type=TriggerType.EVENT,
        trigger_event="opportunity.stage_changed",
        conditions=[
            {
                "field": "amount",
                "operator": "greater_than_or_equal",
                "value": 10000,
            }
        ],
        actions=[
            {
                "action_type": "send_notification",
                "params": {
                    "title": "High-Value Deal Alert: {opportunity_name} (${amount})",
                    "body": "Deal advanced to stage '{stage_name}'. Estimated close date: {expected_close}.",
                    "category": "crm",
                },
            }
        ],
    ),
]


def get_template_by_key(key: str) -> AutomationTemplateDefinition | None:
    for tmpl in TEMPLATES:
        if tmpl.key == key:
            return tmpl
    return None


def list_templates() -> list[AutomationTemplateDefinition]:
    return list(TEMPLATES)
