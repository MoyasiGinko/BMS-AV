"""Business logic services for the Back-Office operations control plane."""

from datetime import datetime
from uuid import UUID

from django.contrib.auth import login
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import HttpRequest

from apps.accounts.models import User
from apps.billing.models import Plan, Subscription
from apps.core.events import publish
from apps.core.models import OutboxEvent
from apps.core.services import record_audit_log
from apps.tenancy.models import Membership, Organization


def start_impersonation(
    *,
    actor: User,
    target_user: User,
    request: HttpRequest,
    reason: str = "",
    organization: Organization | None = None,
) -> None:
    """Start an authenticated impersonation session as target_user.

    Preserves actor credentials in session to display the impersonation banner
    and support safe exit.
    """
    if not (actor.is_staff or actor.is_superuser):
        raise PermissionDenied("Only internal staff can initiate impersonation.")

    # Determine target organization context
    target_org = organization
    if target_org is None:
        membership = (
            Membership.all_tenants.filter(user=target_user, status="active")
            .select_related("organization")
            .first()
        )
        if membership:
            target_org = membership.organization

    org_id = target_org.id if target_org else None

    # Audit log
    if org_id:
        record_audit_log(
            organization_id=org_id,
            action="backoffice.impersonate_start",
            target=target_user,
            changes={
                "impersonator_email": actor.email,
                "target_email": target_user.email,
                "reason": reason,
            },
            actor=actor,
            ip_address=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )

    # Perform Django login as target_user
    login(request, target_user, backend="django.contrib.auth.backends.ModelBackend")

    # Set impersonation session variables (post-login to prevent session cycle clearing)
    request.session["impersonator_id"] = actor.pk
    request.session["impersonator_email"] = actor.email
    request.session["is_impersonating"] = True
    if org_id:
        request.session["active_org_id"] = org_id
    request.session.modified = True


def stop_impersonation(*, request: HttpRequest) -> User:
    """End the active impersonation session and restore the staff operator."""
    impersonator_id = request.session.get("impersonator_id")
    if not impersonator_id:
        raise ValidationError("No active impersonation session found in this browser.")

    staff_user = User.objects.filter(pk=impersonator_id).first()
    if not staff_user or not (staff_user.is_staff or staff_user.is_superuser):
        raise PermissionDenied("Original operator could not be verified.")

    current_user = request.user
    org_id = request.session.get("active_org_id")

    # Audit log
    if org_id:
        record_audit_log(
            organization_id=org_id,
            action="backoffice.impersonate_stop",
            target=current_user,
            changes={
                "impersonator_email": staff_user.email,
                "exited_target_email": getattr(current_user, "email", "anonymous"),
            },
            actor=staff_user,
            ip_address=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )

    # Restore staff user login
    login(request, staff_user, backend="django.contrib.auth.backends.ModelBackend")

    # Clear impersonation flags from session
    for key in ["impersonator_id", "impersonator_email", "is_impersonating", "original_org_id"]:
        request.session.pop(key, None)
    request.session.modified = True

    return staff_user


@transaction.atomic
def override_subscription(
    *,
    actor: User,
    organization: Organization,
    plan_slug: str,
    status: str,
    trial_end: datetime | None = None,
    renews_at: datetime | None = None,
    reason: str,
    ip_address: str | None = None,
    user_agent: str = "",
) -> Subscription:
    """Override a tenant's subscription tier, status, or dates with audit logging."""
    if not (actor.is_staff or actor.is_superuser):
        raise PermissionDenied("Only internal staff can perform subscription overrides.")

    if not reason.strip():
        raise ValidationError("An operational reason is required for subscription overrides.")

    plan = Plan.objects.get(slug=plan_slug)
    sub = Subscription.all_tenants.filter(organization=organization).select_for_update().first()

    if sub is None:
        sub = Subscription.all_tenants.create(
            organization=organization,
            plan=plan,
            status=status,
            trial_end=trial_end,
            renews_at=renews_at,
        )
        old_plan_name = "None"
        old_status = "None"
    else:
        old_plan_name = sub.plan.name
        old_status = sub.status
        sub.plan = plan
        sub.status = status
        sub.trial_end = trial_end
        sub.renews_at = renews_at
        sub.save()

    record_audit_log(
        organization_id=organization.id,
        action="backoffice.subscription_override",
        target=sub,
        changes={
            "old_plan": old_plan_name,
            "new_plan": plan.name,
            "old_status": old_status,
            "new_status": status,
            "reason": reason,
        },
        actor=actor,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    publish(
        "billing.subscription_overridden",
        payload={
            "organization_id": str(organization.public_id),
            "plan_slug": plan.slug,
            "status": status,
            "reason": reason,
        },
        organization_id=organization.id,
        actor_id=actor.pk,
    )

    return sub


@transaction.atomic
def update_tenant_status(
    *,
    actor: User,
    organization: Organization,
    status: str,
    reason: str,
    ip_address: str | None = None,
    user_agent: str = "",
) -> Organization:
    """Change organization status (active, suspended, archived) with mandatory reason."""
    if not (actor.is_staff or actor.is_superuser):
        raise PermissionDenied("Only internal staff can change organization lifecycle status.")

    if not reason.strip():
        raise ValidationError("A reason is required to update tenant status.")

    org = Organization.objects.select_for_update().get(pk=organization.pk)
    old_status = org.status
    org.is_active = status == "active"
    if not isinstance(org.settings, dict):
        org.settings = {}
    org.settings["status"] = status
    org.save(update_fields=["is_active", "settings", "updated_at"])

    record_audit_log(
        organization_id=org.id,
        action="backoffice.tenant_status_update",
        target=org,
        changes={
            "old_status": old_status,
            "new_status": status,
            "reason": reason,
        },
        actor=actor,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    publish(
        "tenancy.organization_status_updated",
        payload={
            "organization_id": str(org.public_id),
            "old_status": old_status,
            "new_status": status,
            "reason": reason,
        },
        organization_id=org.id,
        actor_id=actor.pk,
    )

    return org


@transaction.atomic
def retry_outbox_event(
    *,
    actor: User,
    event_id: str | UUID,
    ip_address: str | None = None,
    user_agent: str = "",
) -> OutboxEvent:
    """Reset a failed Outbox event to pending for immediate Celery re-dispatch."""
    if not (actor.is_staff or actor.is_superuser):
        raise PermissionDenied("Only internal staff can trigger outbox retries.")

    event = OutboxEvent.objects.select_for_update().get(event_id=event_id)
    old_status = event.status
    event.status = OutboxEvent.STATUS_PENDING
    event.retry_count += 1
    event.last_error = ""
    event.save(update_fields=["status", "retry_count", "last_error"])

    if event.organization_id:
        record_audit_log(
            organization_id=event.organization_id,
            action="backoffice.outbox_retry",
            target=event,
            changes={
                "old_status": old_status,
                "retry_count": event.retry_count,
            },
            actor=actor,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    return event
