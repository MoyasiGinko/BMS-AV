import importlib

from django.apps import AppConfig


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

        self._register_approval_handlers()

    def _register_approval_handlers(self) -> None:
        from apps.accounting.models import Expense, ExpenseStatus
        from apps.approvals.models import ApprovalRuleType
        from apps.approvals.registry import approval_handlers

        def _on_expense_approve(*, organization, actor, request, notes="") -> None:
            pass

        def _on_expense_reject(*, organization, actor, request, notes="") -> None:
            exp = Expense.all_tenants.filter(pk=int(request.document_id), organization=organization).first()
            if exp and exp.status == ExpenseStatus.DRAFT:
                exp.status = ExpenseStatus.VOID
                exp.notes = f"{exp.notes}\nRejected in approvals: {notes}".strip()
                exp.save(update_fields=["status", "notes", "updated_at"])

        approval_handlers.register(
            ApprovalRuleType.EXPENSE,
            on_approve=_on_expense_approve,
            on_reject=_on_expense_reject,
        )
