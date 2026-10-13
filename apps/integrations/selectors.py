"""Read-only selectors for import jobs, export jobs, and integration data."""

from __future__ import annotations

import uuid
from typing import Any

from django.db.models import QuerySet
from oauth2_provider.models import AccessToken

from apps.integrations.models import (
    DataRetentionPolicy,
    DataSubjectRequest,
    ExportJob,
    ExternalReference,
    ImportJob,
    InboundWebhookEndpoint,
    InboundWebhookLog,
    IntegrationConnection,
    IntegrationSyncLog,
    OAuthApplication,
    TenantExportJob,
    TenantImportJob,
    WebhookDelivery,
    WebhookDeliveryStatus,
    WebhookEndpoint,
)
from apps.tenancy.models import Organization


def get_import_job(
    organization: Organization,
    *,
    job_id: str | uuid.UUID,
) -> ImportJob | None:
    """Retrieve single ImportJob for an organization."""
    return (
        ImportJob.all_tenants.filter(organization=organization, public_id=job_id)
        .select_related("created_by")
        .first()
    )


def list_import_jobs(
    organization: Organization,
    *,
    entity_type: str | None = None,
) -> QuerySet[ImportJob]:
    """Retrieve chronological list of import jobs for an organization."""
    qs = (
        ImportJob.all_tenants.filter(organization=organization)
        .select_related("created_by")
        .order_by("-created_at")
    )
    if entity_type:
        qs = qs.filter(entity_type=entity_type)
    return qs


def get_export_job(
    organization: Organization,
    *,
    job_id: str | uuid.UUID,
) -> ExportJob | None:
    """Retrieve single ExportJob for an organization."""
    return (
        ExportJob.all_tenants.filter(organization=organization, public_id=job_id)
        .select_related("created_by")
        .first()
    )


def list_export_jobs(
    organization: Organization,
    *,
    entity_type: str | None = None,
) -> QuerySet[ExportJob]:
    """Retrieve chronological list of entity export jobs for an organization."""
    qs = (
        ExportJob.all_tenants.filter(organization=organization)
        .select_related("created_by")
        .order_by("-created_at")
    )
    if entity_type:
        qs = qs.filter(entity_type=entity_type)
    return qs


def get_integrations_summary(organization: Organization) -> dict[str, Any]:
    """Return summary counts for imports and exports hub."""
    imports_qs = ImportJob.all_tenants.filter(organization=organization)
    exports_qs = ExportJob.all_tenants.filter(organization=organization)

    return {
        "total_imports": imports_qs.count(),
        "completed_imports": imports_qs.filter(status="completed").count(),
        "total_exports": exports_qs.count(),
        "recent_imports": imports_qs.order_by("-created_at")[:5],
        "recent_exports": exports_qs.order_by("-created_at")[:5],
    }


def list_webhook_endpoints(
    organization: Organization,
    *,
    is_active: bool | None = None,
) -> QuerySet[WebhookEndpoint]:
    """Retrieve tenant webhook endpoints with creator user prefetched."""
    qs = (
        WebhookEndpoint.all_tenants.filter(organization=organization)
        .select_related("created_by")
        .order_by("-created_at")
    )
    if is_active is not None:
        qs = qs.filter(is_active=is_active)
    return qs


def get_webhook_endpoint(
    organization: Organization,
    *,
    endpoint_id: str | uuid.UUID,
) -> WebhookEndpoint | None:
    """Retrieve single WebhookEndpoint by public UUID or integer ID."""
    qs = WebhookEndpoint.all_tenants.filter(organization=organization).select_related("created_by")
    try:
        val = uuid.UUID(str(endpoint_id))
        return qs.filter(public_id=val).first()
    except ValueError, TypeError:
        if str(endpoint_id).isdigit():
            return qs.filter(id=int(endpoint_id)).first()
        return None


def list_webhook_deliveries(
    organization: Organization,
    *,
    endpoint: WebhookEndpoint | None = None,
    status: str | None = None,
    event_type: str | None = None,
) -> QuerySet[WebhookDelivery]:
    """Retrieve delivery log records with endpoint prefetched."""
    qs = (
        WebhookDelivery.all_tenants.filter(organization=organization)
        .select_related("endpoint")
        .order_by("-created_at")
    )
    if endpoint is not None:
        qs = qs.filter(endpoint=endpoint)
    if status:
        qs = qs.filter(status=status)
    if event_type:
        qs = qs.filter(event_type=event_type)
    return qs


def get_webhook_delivery(
    organization: Organization,
    *,
    delivery_id: str | uuid.UUID,
) -> WebhookDelivery | None:
    """Retrieve a single delivery log entry by public UUID or integer ID."""
    qs = WebhookDelivery.all_tenants.filter(organization=organization).select_related(
        "endpoint", "endpoint__created_by"
    )
    try:
        val = uuid.UUID(str(delivery_id))
        return qs.filter(public_id=val).first()
    except ValueError, TypeError:
        if str(delivery_id).isdigit():
            return qs.filter(id=int(delivery_id)).first()
        return None


def get_webhooks_summary(organization: Organization) -> dict[str, Any]:
    """Return metrics for the webhooks dashboard overview."""
    endpoints_qs = WebhookEndpoint.all_tenants.filter(organization=organization)
    deliveries_qs = WebhookDelivery.all_tenants.filter(organization=organization)

    total_deliveries = deliveries_qs.count()
    success_deliveries = deliveries_qs.filter(status=WebhookDeliveryStatus.SUCCESS).count()
    success_rate = round((success_deliveries / total_deliveries) * 100, 1) if total_deliveries > 0 else 100.0

    return {
        "total_endpoints": endpoints_qs.count(),
        "active_endpoints": endpoints_qs.filter(is_active=True).count(),
        "disabled_endpoints": endpoints_qs.filter(is_active=False).count(),
        "total_deliveries": total_deliveries,
        "success_deliveries": success_deliveries,
        "failed_deliveries": deliveries_qs.filter(status=WebhookDeliveryStatus.FAILED).count(),
        "retrying_deliveries": deliveries_qs.filter(status=WebhookDeliveryStatus.RETRYING).count(),
        "success_rate": success_rate,
        "recent_deliveries": deliveries_qs.select_related("endpoint").order_by("-created_at")[:10],
    }


def list_integration_connections(
    organization: Organization,
    *,
    connector_type: str | None = None,
    status: str | None = None,
) -> QuerySet[IntegrationConnection]:
    """Retrieve integration connections for an organization."""
    qs = IntegrationConnection.all_tenants.filter(organization=organization).order_by("-created_at")
    if connector_type:
        qs = qs.filter(connector_type=connector_type)
    if status:
        qs = qs.filter(status=status)
    return qs


def get_integration_connection(
    organization: Organization,
    *,
    connection_id: str | uuid.UUID,
) -> IntegrationConnection | None:
    """Retrieve single IntegrationConnection by ID or public_id."""
    qs = IntegrationConnection.all_tenants.filter(organization=organization)
    if isinstance(connection_id, uuid.UUID):
        return qs.filter(public_id=connection_id).first()
    try:
        val_uuid = uuid.UUID(str(connection_id))
        return qs.filter(public_id=val_uuid).first()
    except ValueError, AttributeError:
        if str(connection_id).isdigit():
            return qs.filter(id=int(connection_id)).first()
        return None


def list_external_references(
    organization: Organization,
    *,
    connection: IntegrationConnection | None = None,
    entity_type: str | None = None,
    internal_id: str | None = None,
) -> QuerySet[ExternalReference]:
    """Retrieve external reference mappings."""
    qs = (
        ExternalReference.all_tenants.filter(organization=organization)
        .select_related("connection")
        .order_by("-last_synced_at")
    )
    if connection:
        qs = qs.filter(connection=connection)
    if entity_type:
        qs = qs.filter(entity_type=entity_type)
    if internal_id:
        qs = qs.filter(internal_id=internal_id)
    return qs


def get_external_reference(
    organization: Organization,
    *,
    connection: IntegrationConnection,
    entity_type: str,
    external_id: str,
) -> ExternalReference | None:
    """Retrieve single external reference mapping by connection, entity type, and external ID."""
    return ExternalReference.all_tenants.filter(
        organization=organization,
        connection=connection,
        entity_type=entity_type,
        external_id=external_id,
    ).first()


def find_external_reference_by_internal(
    organization: Organization,
    *,
    entity_type: str,
    internal_id: str,
    connection: IntegrationConnection | None = None,
) -> ExternalReference | None:
    """Find external reference mapping by internal entity ID."""
    qs = ExternalReference.all_tenants.filter(
        organization=organization,
        entity_type=entity_type,
        internal_id=internal_id,
    )
    if connection:
        qs = qs.filter(connection=connection)
    return qs.first()


def list_sync_logs(
    organization: Organization,
    *,
    connection: IntegrationConnection | None = None,
    status: str | None = None,
    limit: int = 50,
) -> QuerySet[IntegrationSyncLog]:
    """Retrieve chronological sync execution audit logs."""
    qs = (
        IntegrationSyncLog.all_tenants.filter(organization=organization)
        .select_related("connection")
        .order_by("-created_at")
    )
    if connection:
        qs = qs.filter(connection=connection)
    if status:
        qs = qs.filter(status=status)
    return qs[:limit]


# --- OAuth Selectors ---


def list_oauth_applications(
    organization: Organization,
    *,
    is_active: bool | None = None,
) -> QuerySet[OAuthApplication]:
    """List OAuth2 applications registered for a tenant organization."""
    qs = OAuthApplication.all_tenants.filter(organization=organization).order_by("-created_at")
    if is_active is not None:
        qs = qs.filter(is_active=is_active)
    return qs


def get_oauth_application(
    organization: Organization,
    *,
    application_id: str | int | uuid.UUID | None = None,
    client_id: str | None = None,
) -> OAuthApplication | None:
    """Retrieve an OAuth application by ID or client_id within tenant scope."""
    qs = OAuthApplication.all_tenants.filter(organization=organization)
    if client_id:
        return qs.filter(client_id=client_id).first()
    if application_id:
        try:
            val_uuid = uuid.UUID(str(application_id))
            return qs.filter(public_id=val_uuid).first()
        except ValueError, AttributeError:
            if str(application_id).isdigit():
                return qs.filter(id=int(application_id)).first()
    return None


def get_oauth_application_by_client_id(client_id: str) -> OAuthApplication | None:
    """Retrieve an OAuth application globally by client_id."""
    return OAuthApplication.all_tenants.select_related("organization").filter(client_id=client_id).first()


def list_user_authorized_tokens(
    user: Any,
    organization: Organization,
) -> QuerySet[AccessToken]:
    """List active OAuth tokens granted by a user in the organization."""
    return (
        AccessToken.objects.filter(
            user=user,
            application__organization=organization,
        )
        .select_related("application")
        .order_by("-created")
    )


# --- Inbound Webhook Selectors ---


def list_inbound_webhook_endpoints(
    organization: Organization,
    *,
    provider: str | None = None,
    status: str | None = None,
) -> QuerySet[InboundWebhookEndpoint]:
    """List inbound webhook endpoints configured for an organization."""
    qs = InboundWebhookEndpoint.all_tenants.filter(organization=organization).order_by("-created_at")
    if provider:
        qs = qs.filter(provider=provider)
    if status:
        qs = qs.filter(status=status)
    return qs


def get_inbound_webhook_endpoint(
    organization: Organization,
    *,
    endpoint_id: str | int | uuid.UUID,
) -> InboundWebhookEndpoint | None:
    """Retrieve an inbound webhook endpoint within tenant scope."""
    qs = InboundWebhookEndpoint.all_tenants.filter(organization=organization)
    try:
        val_uuid = uuid.UUID(str(endpoint_id))
        return qs.filter(public_id=val_uuid).first()
    except ValueError, AttributeError:
        if str(endpoint_id).isdigit():
            return qs.filter(id=int(endpoint_id)).first()
    return None


def get_inbound_webhook_endpoint_public(public_id: str | uuid.UUID) -> InboundWebhookEndpoint | None:
    """Retrieve an active inbound webhook endpoint globally for receiving webhooks."""
    try:
        val_uuid = uuid.UUID(str(public_id))
        return (
            InboundWebhookEndpoint.all_tenants.select_related("organization")
            .filter(public_id=val_uuid)
            .first()
        )
    except ValueError, AttributeError:
        return None


def list_inbound_webhook_logs(
    organization: Organization,
    *,
    endpoint: InboundWebhookEndpoint | None = None,
    verification_status: str | None = None,
    limit: int = 50,
) -> QuerySet[InboundWebhookLog]:
    """Retrieve audit log history for inbound webhooks."""
    qs = (
        InboundWebhookLog.all_tenants.filter(organization=organization)
        .select_related("endpoint")
        .order_by("-created_at")
    )
    if endpoint:
        qs = qs.filter(endpoint=endpoint)
    if verification_status:
        qs = qs.filter(verification_status=verification_status)
    return qs[:limit]


# --- Data Portability Selectors ---


def list_tenant_export_jobs(
    organization: Organization,
    *,
    limit: int = 50,
) -> QuerySet[TenantExportJob]:
    """Retrieve full-tenant data export jobs for an organization."""
    return (
        TenantExportJob.all_tenants.filter(organization=organization)
        .select_related("requested_by")
        .order_by("-created_at")[:limit]
    )


def get_tenant_export_job(
    organization: Organization,
    *,
    job_id: str | uuid.UUID,
) -> TenantExportJob | None:
    """Retrieve a single tenant export job within organization scope."""
    qs = TenantExportJob.all_tenants.filter(organization=organization)
    try:
        val_uuid = uuid.UUID(str(job_id))
        return qs.filter(public_id=val_uuid).first()
    except (ValueError, AttributeError):
        if str(job_id).isdigit():
            return qs.filter(id=int(job_id)).first()
    return None


def list_tenant_import_jobs(
    organization: Organization,
    *,
    limit: int = 50,
) -> QuerySet[TenantImportJob]:
    """Retrieve full-tenant data import jobs for an organization."""
    return (
        TenantImportJob.all_tenants.filter(organization=organization)
        .select_related("imported_by")
        .order_by("-created_at")[:limit]
    )


def get_tenant_import_job(
    organization: Organization,
    *,
    job_id: str | uuid.UUID,
) -> TenantImportJob | None:
    """Retrieve a single tenant import job within organization scope."""
    qs = TenantImportJob.all_tenants.filter(organization=organization)
    try:
        val_uuid = uuid.UUID(str(job_id))
        return qs.filter(public_id=val_uuid).first()
    except (ValueError, AttributeError):
        if str(job_id).isdigit():
            return qs.filter(id=int(job_id)).first()
    return None


# --- Data Retention Selectors ---


def get_or_create_retention_policy(organization: Organization) -> DataRetentionPolicy:
    """Retrieve existing retention policy or initialize default policy for organization."""
    policy = DataRetentionPolicy.all_tenants.filter(organization=organization).first()
    if policy is None:
        policy = DataRetentionPolicy.objects.create(
            organization=organization,
            audit_log_retention_days=365,
            webhook_log_retention_days=90,
            sync_log_retention_days=90,
            export_file_retention_days=30,
            is_active=True,
        )
    return policy


def list_active_retention_policies() -> QuerySet[DataRetentionPolicy]:
    """Retrieve all active data retention policies across tenants for background cleanup."""
    return DataRetentionPolicy.all_tenants.filter(is_active=True).select_related("organization")


# --- GDPR / Privacy Selectors ---


def list_data_subject_requests(
    organization: Organization,
    *,
    request_type: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> QuerySet[DataSubjectRequest]:
    """Retrieve GDPR Data Subject Requests for an organization."""
    qs = (
        DataSubjectRequest.all_tenants.filter(organization=organization)
        .select_related("submitted_by", "processed_by")
        .order_by("-created_at")
    )
    if request_type:
        qs = qs.filter(request_type=request_type)
    if status:
        qs = qs.filter(status=status)
    return qs[:limit]


def get_data_subject_request(
    organization: Organization,
    *,
    request_id: str | uuid.UUID,
) -> DataSubjectRequest | None:
    """Retrieve single GDPR Data Subject Request within organization scope."""
    qs = DataSubjectRequest.all_tenants.filter(organization=organization)
    try:
        val_uuid = uuid.UUID(str(request_id))
        return qs.filter(public_id=val_uuid).first()
    except (ValueError, AttributeError):
        if str(request_id).isdigit():
            return qs.filter(id=int(request_id)).first()
    return None


def find_subject_personal_records(
    organization: Organization,
    *,
    email: str,
) -> dict[str, Any]:
    """Find all personal records associated with an email across domain modules."""
    clean_email = email.strip().lower()

    # Customers
    from apps.customers.models import Customer, CustomerContact

    customers = list(
        Customer.all_tenants.filter(organization=organization, email__iexact=clean_email)
    )
    contacts = list(
        CustomerContact.all_tenants.filter(
            organization=organization, email__iexact=clean_email
        ).select_related("customer")
    )

    # CRM Leads
    from apps.crm.models import Lead

    leads = list(Lead.all_tenants.filter(organization=organization, email__iexact=clean_email))

    # HR Employees
    from apps.hr.models import Employee

    employees = list(
        Employee.all_tenants.filter(
            organization=organization,
            work_email__iexact=clean_email,
        )
        | Employee.all_tenants.filter(
            organization=organization,
            personal_email__iexact=clean_email,
        )
    )

    # Sales invoices & payments count
    from apps.sales.models import SalesInvoice

    customer_pks = [c.pk for c in customers] + [
        contact.customer.pk for contact in contacts if contact.customer_id
    ]
    invoices_count = 0
    if customer_pks:
        invoices_count = SalesInvoice.all_tenants.filter(
            organization=organization, customer_id__in=customer_pks
        ).count()

    return {
        "email": clean_email,
        "customers": customers,
        "contacts": contacts,
        "leads": leads,
        "employees": employees,
        "sales_invoices_count": invoices_count,
        "total_matches": len(customers) + len(contacts) + len(leads) + len(employees),
    }

