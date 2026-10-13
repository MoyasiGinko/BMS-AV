# Approvals Engine Module (`apps.approvals`)

The Approvals Engine provides a multi-tenant, configurable approval workflow system for Business OS. It enables organizations to establish rule-based controls across business operations (such as Purchase Orders over $X, Expenses over $Y, Payroll runs, and Sales discounts) with a full-featured approval inbox, audit trails, and REST API.

## Models
- **`ApprovalRule`**: Tenant-scoped configurable rule specifying document/event type (`purchase_order`, `expense`, `payroll`, `discount`), monetary/percentage threshold (`min_amount`, `min_discount_percent`), designated approver (`approver_role` or `approver_user`), priority (`sort_order`), and active status.
- **`ApprovalRequest`**: A specific document approval instance tracking status (`pending`, `approved`, `rejected`, `cancelled`), requester, assigned approver, financial amount, discount percentage, and decision attribution (`reviewed_by`, `reviewed_at`, `decision_notes`).
- **`ApprovalHistory`**: Immutable chronological audit log of actions taken on an approval request (`submitted`, `approved`, `rejected`, `cancelled`).

## Services (`apps/approvals/services.py`)
- `create_approval_rule`: Creates a new approval rule with threshold parameters.
- `update_approval_rule`: Updates rule configuration.
- `delete_approval_rule`: Deletes an approval rule.
- `evaluate_approval_required`: Checks whether a given transaction matches any active rule.
- `request_approval`: Evaluates rules and creates a pending `ApprovalRequest` with initial history.
- `approve_request`: Validates approver authority, sets status to `approved`, runs registered callbacks, records history, and emits `ApprovalRequestApproved`.
- `reject_request`: Validates approver authority, sets status to `rejected`, runs registered callbacks, records history, and emits `ApprovalRequestRejected`.
- `cancel_request`: Cancels a pending approval request.

## Decoupled Domain Handlers (`apps/approvals/registry.py`)
Higher-level domain modules register callbacks without circular imports:
```python
from apps.approvals.registry import approval_handlers
from apps.approvals.models import ApprovalRuleType

approval_handlers.register(
    ApprovalRuleType.PURCHASE_ORDER,
    on_approve=_on_po_approve,
    on_reject=_on_po_reject,
)
```

## Domain Events (`apps/approvals/events.py`)
- `ApprovalRuleCreated`
- `ApprovalRuleUpdated`
- `ApprovalRuleDeleted`
- `ApprovalRequested`
- `ApprovalRequestApproved`
- `ApprovalRequestRejected`
- `ApprovalRequestCancelled`

## Permissions
- `approvals.view`: View the inbox, requests, and history.
- `approvals.approve`: Approve or reject submitted requests.
- `approvals.manage`: Create, edit, and delete approval rules.

## Web UI & REST API
- Web UI:
  - `/approvals/`: Inbox with quick actions, status filters, and search.
  - `/approvals/requests/<id>/`: Detail view with audit timeline and decision forms.
  - `/approvals/rules/`: Policy rules management list.
  - `/approvals/rules/new/`: Rule creator.
  - `/approvals/history/`: Organization audit trail.
- REST API (`/api/v1/approvals/`):
  - `/api/v1/approvals/rules/`: CRUD for approval policies.
  - `/api/v1/approvals/requests/`: List and detail for requests.
  - `/api/v1/approvals/requests/<id>/approve/`: POST action to approve.
  - `/api/v1/approvals/requests/<id>/reject/`: POST action to reject.
  - `/api/v1/approvals/requests/<id>/cancel/`: POST action to cancel.
