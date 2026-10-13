"""Django app configuration for Payroll module."""

from django.apps import AppConfig


class PayrollConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.payroll"
    verbose_name = "Payroll"

    def ready(self) -> None:
        self._register_approval_handlers()

    def _register_approval_handlers(self) -> None:
        from apps.approvals.models import ApprovalRuleType
        from apps.approvals.registry import approval_handlers
        from apps.payroll import services as payroll_services
        from apps.payroll.models import PayrollRun, PayrollRunStatus

        def _on_payroll_approve(*, organization, actor, request, notes="") -> None:
            run = PayrollRun.all_tenants.filter(pk=int(request.document_id), organization=organization).first()
            if run and run.status in (PayrollRunStatus.DRAFT, PayrollRunStatus.REVIEWED):
                payroll_services.approve_payroll_run(
                    payroll_run=run,
                    actor=actor,
                )

        def _on_payroll_reject(*, organization, actor, request, notes="") -> None:
            run = PayrollRun.all_tenants.filter(pk=int(request.document_id), organization=organization).first()
            if run and run.status in (PayrollRunStatus.DRAFT, PayrollRunStatus.REVIEWED):
                payroll_services.cancel_payroll_run(
                    payroll_run=run,
                    actor=actor,
                )

        approval_handlers.register(
            ApprovalRuleType.PAYROLL,
            on_approve=_on_payroll_approve,
            on_reject=_on_payroll_reject,
        )
