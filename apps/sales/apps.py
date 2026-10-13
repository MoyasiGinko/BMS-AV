import importlib

from django.apps import AppConfig


class SalesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.sales"
    verbose_name = "Sales & Invoicing"

    def ready(self) -> None:
        perm_mod = importlib.import_module("apps.sales.permissions")
        perm_mod.register_sales_permissions()
        self._register_approval_handlers()

    def _register_approval_handlers(self) -> None:
        from apps.approvals.models import ApprovalRuleType
        from apps.approvals.registry import approval_handlers
        from apps.sales.models import SalesOrder

        def _on_discount_approve(*, organization, actor, request, notes="") -> None:
            so = SalesOrder.all_tenants.filter(pk=int(request.document_id), organization=organization).first()
            if so:
                so.notes = f"{so.notes}\n[Approved Discount]: {notes}".strip()
                so.save(update_fields=["notes", "updated_at"])

        def _on_discount_reject(*, organization, actor, request, notes="") -> None:
            so = SalesOrder.all_tenants.filter(pk=int(request.document_id), organization=organization).first()
            if so:
                so.notes = f"{so.notes}\n[Rejected Discount]: {notes}".strip()
                so.save(update_fields=["notes", "updated_at"])

        approval_handlers.register(
            ApprovalRuleType.DISCOUNT,
            on_approve=_on_discount_approve,
            on_reject=_on_discount_reject,
        )
