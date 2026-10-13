"""Django app configuration for Payroll module."""

from django.apps import AppConfig


def _on_payroll_approve(*, organization, actor, request, notes="") -> None:
    from apps.payroll import services as payroll_services  # noqa: PLC0415
    from apps.payroll.models import PayrollRun, PayrollRunStatus  # noqa: PLC0415

    doc_id = str(request.document_id)
    if doc_id.isdigit():
        run = PayrollRun.all_tenants.filter(pk=int(doc_id), organization=organization).first()
    else:
        run = PayrollRun.all_tenants.filter(run_number=doc_id, organization=organization).first()

    if run and run.status in (PayrollRunStatus.DRAFT, PayrollRunStatus.REVIEWED):
        payroll_services.approve_payroll_run(
            payroll_run=run,
            actor=actor,
        )


def _on_payroll_reject(*, organization, actor, request, notes="") -> None:
    from apps.payroll import services as payroll_services  # noqa: PLC0415
    from apps.payroll.models import PayrollRun, PayrollRunStatus  # noqa: PLC0415

    doc_id = str(request.document_id)
    if doc_id.isdigit():
        run = PayrollRun.all_tenants.filter(pk=int(doc_id), organization=organization).first()
    else:
        run = PayrollRun.all_tenants.filter(run_number=doc_id, organization=organization).first()

    if run and run.status in (PayrollRunStatus.DRAFT, PayrollRunStatus.REVIEWED):
        payroll_services.cancel_payroll_run(
            payroll_run=run,
            actor=actor,
        )


class PayrollConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.payroll"
    verbose_name = "Payroll"

    def ready(self) -> None:
        from apps.approvals.constants import ApprovalRuleType  # noqa: PLC0415
        from apps.approvals.registry import approval_handlers  # noqa: PLC0415

        approval_handlers.register(
            ApprovalRuleType.PAYROLL,
            on_approve=_on_payroll_approve,
            on_reject=_on_payroll_reject,
        )
