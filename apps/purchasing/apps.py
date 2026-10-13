from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


def _on_po_approve(*, organization, actor, request, notes="") -> None:
    from apps.purchasing import services as purchasing_services  # noqa: PLC0415
    from apps.purchasing.models import PurchaseOrder, PurchaseOrderStatus  # noqa: PLC0415

    doc_id = str(request.document_id)
    if doc_id.isdigit():
        po = PurchaseOrder.all_tenants.filter(pk=int(doc_id), organization=organization).first()
    else:
        po = PurchaseOrder.all_tenants.filter(order_number=doc_id, organization=organization).first()

    if po and po.status in (PurchaseOrderStatus.DRAFT, PurchaseOrderStatus.SUBMITTED):
        purchasing_services.approve_purchase_order(
            organization=organization,
            purchase_order=po,
            actor=actor,
        )


def _on_po_reject(*, organization, actor, request, notes="") -> None:
    from apps.purchasing import services as purchasing_services  # noqa: PLC0415
    from apps.purchasing.models import PurchaseOrder, PurchaseOrderStatus  # noqa: PLC0415

    doc_id = str(request.document_id)
    if doc_id.isdigit():
        po = PurchaseOrder.all_tenants.filter(pk=int(doc_id), organization=organization).first()
    else:
        po = PurchaseOrder.all_tenants.filter(order_number=doc_id, organization=organization).first()

    if po and po.status in (PurchaseOrderStatus.DRAFT, PurchaseOrderStatus.SUBMITTED):
        purchasing_services.cancel_purchase_order(
            organization=organization,
            purchase_order=po,
            actor=actor,
        )


class PurchasingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.purchasing"
    verbose_name = _("Purchasing & Vendor Management")

    def ready(self) -> None:
        from apps.approvals.constants import ApprovalRuleType  # noqa: PLC0415
        from apps.approvals.registry import approval_handlers  # noqa: PLC0415

        approval_handlers.register(
            ApprovalRuleType.PURCHASE_ORDER,
            on_approve=_on_po_approve,
            on_reject=_on_po_reject,
        )
