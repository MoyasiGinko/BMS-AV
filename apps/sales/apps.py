import importlib

from django.apps import AppConfig


def _on_discount_approve(*, organization, actor, request, notes="") -> None:
    from apps.sales.models import SalesOrder  # noqa: PLC0415

    doc_id = str(request.document_id)
    if doc_id.isdigit():
        so = SalesOrder.all_tenants.filter(pk=int(doc_id), organization=organization).first()
    else:
        so = SalesOrder.all_tenants.filter(order_number=doc_id, organization=organization).first()

    if so:
        so.notes = f"{so.notes}\n[Approved Discount]: {notes}".strip()
        so.save(update_fields=["notes", "updated_at"])


def _on_discount_reject(*, organization, actor, request, notes="") -> None:
    from apps.sales.models import SalesOrder  # noqa: PLC0415

    doc_id = str(request.document_id)
    if doc_id.isdigit():
        so = SalesOrder.all_tenants.filter(pk=int(doc_id), organization=organization).first()
    else:
        so = SalesOrder.all_tenants.filter(order_number=doc_id, organization=organization).first()

    if so:
        so.notes = f"{so.notes}\n[Rejected Discount]: {notes}".strip()
        so.save(update_fields=["notes", "updated_at"])


class SalesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.sales"
    verbose_name = "Sales & Invoicing"

    def ready(self) -> None:
        perm_mod = importlib.import_module("apps.sales.permissions")
        perm_mod.register_sales_permissions()

        from apps.approvals.constants import ApprovalRuleType  # noqa: PLC0415
        from apps.approvals.registry import approval_handlers  # noqa: PLC0415

        approval_handlers.register(
            ApprovalRuleType.DISCOUNT,
            on_approve=_on_discount_approve,
            on_reject=_on_discount_reject,
        )
