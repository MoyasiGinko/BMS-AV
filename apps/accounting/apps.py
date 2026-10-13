import importlib

from django.apps import AppConfig


def _on_expense_approve(*, organization, actor, request, notes="") -> None:
    pass


def _on_expense_reject(*, organization, actor, request, notes="") -> None:
    from apps.accounting.models import Expense, ExpenseStatus  # noqa: PLC0415

    doc_id = str(request.document_id)
    if doc_id.isdigit():
        exp = Expense.all_tenants.filter(pk=int(doc_id), organization=organization).first()
    else:
        exp = Expense.all_tenants.filter(expense_number=doc_id, organization=organization).first()

    if exp and exp.status == ExpenseStatus.DRAFT:
        exp.status = ExpenseStatus.VOID
        exp.notes = f"{exp.notes}\nRejected in approvals: {notes}".strip()
        exp.save(update_fields=["status", "notes", "updated_at"])


class AccountingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounting"
    label = "accounting"

    def ready(self) -> None:
        perm_mod = importlib.import_module("apps.accounting.permissions")
        perm_mod.register_accounting_permissions()

        core_hooks_mod = importlib.import_module("apps.core.hooks")
        services_mod = importlib.import_module("apps.accounting.services")
        core_hooks_mod.register_provisioning_hook(services_mod.provision_accounting)

        from apps.approvals.constants import ApprovalRuleType  # noqa: PLC0415
        from apps.approvals.registry import approval_handlers  # noqa: PLC0415

        approval_handlers.register(
            ApprovalRuleType.EXPENSE,
            on_approve=_on_expense_approve,
            on_reject=_on_expense_reject,
        )
