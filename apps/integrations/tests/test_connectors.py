"""Comprehensive test suite for the Integration Connector Framework (P5-05)."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.core.tenant_context import tenant_context
from apps.integrations import selectors, services, tasks
from apps.integrations.connectors import (
    CsvImportConnector,
    FakePaymentsConnector,
    FakeSmsConnector,
    GenericRestConnector,
    SmtpEmailConnector,
    ZapierCompatConnector,
    connector_registry,
)
from apps.integrations.models import (
    ExternalReference,
    IntegrationConnection,
    SyncStatus,
)
from apps.tenancy.models import Membership, Organization, Role

User = get_user_model()


@pytest.fixture
def connector_setup(db: Any) -> dict[str, Any]:
    """Fixture providing multi-tenant setups and permission roles."""
    org1 = Organization.objects.create(name="Alpha Corp", slug="alpha-corp")
    org2 = Organization.objects.create(name="Beta Ltd", slug="beta-ltd")

    user_admin = User.objects.create_user(
        email="admin@alphacorp.com",
        password="Password123!",
    )
    role_admin = Role.objects.create(
        organization=org1,
        name="Integration Admin",
        permissions=[
            "integrations.view",
            "integrations.manage",
            "integrations.sync",
            "integrations.import",
            "integrations.export",
        ],
    )
    Membership.objects.create(
        organization=org1,
        user=user_admin,
        role=role_admin,
        is_owner=True,
        status="active",
    )

    user_viewer = User.objects.create_user(
        email="viewer@alphacorp.com",
        password="Password123!",
    )
    role_viewer = Role.objects.create(
        organization=org1,
        name="Integration Viewer",
        permissions=["integrations.view"],
    )
    Membership.objects.create(
        organization=org1,
        user=user_viewer,
        role=role_viewer,
        is_owner=False,
        status="active",
    )

    # Org2 member
    user_org2 = User.objects.create_user(
        email="owner@betaltd.com",
        password="Password123!",
    )
    role_org2 = Role.objects.create(
        organization=org2,
        name="Org2 Admin",
        permissions=[
            "integrations.view",
            "integrations.manage",
            "integrations.sync",
        ],
    )
    Membership.objects.create(
        organization=org2,
        user=user_org2,
        role=role_org2,
        is_owner=True,
        status="active",
    )

    return {
        "org1": org1,
        "org2": org2,
        "user_admin": user_admin,
        "user_viewer": user_viewer,
        "user_org2": user_org2,
    }


# =========================================================================
# 1. Connector Registry & Discovery Tests
# =========================================================================


class TestConnectorRegistry:
    def test_registered_default_connectors(self) -> None:
        all_conn = connector_registry.get_all()
        expected = [
            "generic_rest",
            "csv_import",
            "fake_payments",
            "fake_sms",
            "smtp_email",
            "zapier_compat",
        ]
        for key in expected:
            assert key in all_conn
            connector = connector_registry.get(key)
            assert connector.connector_type == key
            assert connector.name != ""
            assert connector.description != ""

    def test_unknown_connector_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown integration connector"):
            connector_registry.get("non_existent_connector_xyz")

    def test_gallery_metadata(self) -> None:
        gallery = connector_registry.get_gallery_metadata()
        assert len(gallery) >= 6
        types = [item["connector_type"] for item in gallery]
        assert "generic_rest" in types
        assert "fake_payments" in types


# =========================================================================
# 2. Connector Implementations Unit Tests
# =========================================================================


class TestConnectorImplementations:
    def test_generic_rest_connector(self, connector_setup: dict[str, Any]) -> None:
        org = connector_setup["org1"]
        conn = IntegrationConnection(
            organization=org,
            name="REST API Test",
            connector_type="generic_rest",
            config={"base_url": "https://api.example.com", "auth_type": "bearer"},
        )
        conn.credentials = {"token": "secret_bearer_token"}

        connector = GenericRestConnector()
        # Test connection success
        res_test = connector.test_connection(conn)
        assert res_test.success is True
        assert "HTTP 200 OK" in res_test.message

        # Test connection failure on missing token
        conn_no_token = IntegrationConnection(
            organization=org,
            name="REST No Token",
            connector_type="generic_rest",
            config={"base_url": "https://api.example.com", "auth_type": "bearer"},
        )
        assert connector.test_connection(conn_no_token).success is False

        # Inbound sync
        res_sync = connector.sync(conn, direction="inbound")
        assert res_sync.success is True
        assert res_sync.records_processed > 0
        assert "items" in res_sync.data

        # Outbound sync
        res_out = connector.sync(conn, direction="outbound")
        assert res_out.success is True
        assert res_out.records_processed > 0

        # Actions
        res_ping = connector.execute_action(conn, "ping")
        assert res_ping.success is True

        res_push = connector.execute_action(conn, "push_entity", {"id": "123"})
        assert res_push.success is True
        assert res_push.data["remote_id"] == "ext_123"

    def test_csv_import_connector(self, connector_setup: dict[str, Any]) -> None:
        org = connector_setup["org1"]
        conn = IntegrationConnection(
            organization=org,
            name="Products CSV Ingestion",
            connector_type="csv_import",
            config={"entity_type": "products", "delimiter": ","},
        )
        connector = CsvImportConnector()

        res_test = connector.test_connection(conn)
        assert res_test.success is True

        # Test sync with valid CSV content
        raw_csv = "sku,name,price\nPROD-1,Widget A,10.00\nPROD-2,Widget B,20.00"
        res_sync = connector.sync(conn, params={"csv_content": raw_csv})
        assert res_sync.success is True
        assert res_sync.records_processed == 2

    def test_fake_payments_connector(self, connector_setup: dict[str, Any]) -> None:
        org = connector_setup["org1"]
        conn = IntegrationConnection(
            organization=org,
            name="Sandbox Payments",
            connector_type="fake_payments",
            config={"currency": "USD"},
        )
        conn.credentials = {"api_key": "sb_key_12345", "merchant_id": "mch_test"}
        connector = FakePaymentsConnector()

        res_test = connector.test_connection(conn)
        assert res_test.success is True

        # Charge action
        res_charge = connector.execute_action(
            conn,
            "charge",
            {"amount": Decimal("150.00"), "currency": "USD"},
        )
        assert res_charge.success is True
        txn_id = res_charge.data["transaction_id"]
        assert txn_id.startswith("txn_sb_")

        # Refund action
        res_refund = connector.execute_action(conn, "refund", {"transaction_id": txn_id})
        assert res_refund.success is True
        assert res_refund.data["status"] == "refunded"

        # Verify action
        res_ver = connector.execute_action(conn, "verify_payment", {"transaction_id": txn_id})
        assert res_ver.success is True

    def test_fake_sms_connector(self, connector_setup: dict[str, Any]) -> None:
        org = connector_setup["org1"]
        conn = IntegrationConnection(
            organization=org,
            name="Sandbox SMS",
            connector_type="fake_sms",
            config={"sender_id": "+15550199"},
        )
        conn.credentials = {"account_sid": "AC_mock_sid", "auth_token": "mock_token"}
        connector = FakeSmsConnector()
        connector.clear_outbox()

        res_test = connector.test_connection(conn)
        assert res_test.success is True

        # Send SMS action
        res_send = connector.execute_action(
            conn,
            "send_sms",
            {"to": "+15550100", "message": "Your OTP code is 492041"},
        )
        assert res_send.success is True
        msg_id = res_send.data["id"]
        assert len(connector.outbox) == 1

        # Check delivery status
        res_status = connector.execute_action(
            conn,
            "get_delivery_status",
            {"message_id": msg_id},
        )
        assert res_status.success is True
        assert res_status.data["status"] == "delivered"

    def test_smtp_email_connector(self, connector_setup: dict[str, Any]) -> None:
        org = connector_setup["org1"]
        conn = IntegrationConnection(
            organization=org,
            name="Acme Custom SMTP",
            connector_type="smtp_email",
            config={"host": "smtp.mailgun.org", "port": 587, "from_email": "alerts@acme.com"},
        )
        conn.credentials = {"username": "postmaster@acme.com", "password": "SuperSecretPassword"}
        connector = SmtpEmailConnector()
        connector.clear_outbox()

        res_test = connector.test_connection(conn)
        assert res_test.success is True

        # Send email action
        res_send = connector.execute_action(
            conn,
            "send_email",
            {
                "to": ["customer@example.com"],
                "subject": "Invoice Paid",
                "body": "Thank you for your payment.",
            },
        )
        assert res_send.success is True
        assert len(connector.outbox) == 1
        assert connector.outbox[0]["subject"] == "Invoice Paid"

    def test_zapier_compat_connector(self, connector_setup: dict[str, Any]) -> None:
        org = connector_setup["org1"]
        conn = IntegrationConnection(
            organization=org,
            name="Zapier REST Hook Provider",
            connector_type="zapier_compat",
            config={"api_key": "zap_sec_99182"},
        )
        connector = ZapierCompatConnector()

        res_test = connector.test_connection(conn)
        assert res_test.success is True

        # Subscribe action
        res_sub = connector.execute_action(
            conn,
            "subscribe",
            {"event": "sale.confirmed", "target_url": "https://hooks.zapier.com/hooks/catch/123/abc"},
        )
        assert res_sub.success is True
        hook_id = res_sub.data["id"]

        # Sample action
        res_sample = connector.execute_action(conn, "get_sample", {"event": "sale.confirmed"})
        assert res_sample.success is True
        assert "grand_total" in res_sample.data

        # Unsubscribe action
        res_unsub = connector.execute_action(conn, "unsubscribe", {"id": hook_id})
        assert res_unsub.success is True


# =========================================================================
# 3. Model Properties & Encryption Tests
# =========================================================================


class TestConnectionModelAndEncryption:
    def test_credentials_encryption_at_rest(self, connector_setup: dict[str, Any]) -> None:
        org = connector_setup["org1"]
        conn = IntegrationConnection.objects.create(
            organization=org,
            name="Encrypted REST Connection",
            connector_type="generic_rest",
            config={"base_url": "https://api.secure.com"},
        )
        secret_payload = {"api_key": "live_key_9999", "secret": "ultra_confidential_pass"}
        conn.credentials = secret_payload
        conn.save()

        # Reload directly from database to test raw DB column
        raw_conn = IntegrationConnection.all_tenants.get(pk=conn.pk)
        # Raw encrypted_credentials must NOT be plaintext or contain secret
        assert raw_conn.encrypted_credentials != ""
        assert "live_key_9999" not in raw_conn.encrypted_credentials
        assert "ultra_confidential_pass" not in raw_conn.encrypted_credentials

        # Accessing property decrypts back into original dictionary
        assert raw_conn.credentials == secret_payload

    def test_external_reference_unique_constraint(self, connector_setup: dict[str, Any]) -> None:
        org = connector_setup["org1"]
        conn = IntegrationConnection.objects.create(
            organization=org,
            name="Shopify Sync",
            connector_type="generic_rest",
        )
        ExternalReference.objects.create(
            organization=org,
            connection=conn,
            entity_type="product",
            internal_id="prod_101",
            external_id="ext_shopify_5501",
        )

        # Duplicate external_id for same org, connection, and entity_type must fail
        with pytest.raises(IntegrityError):
            ExternalReference.objects.create(
                organization=org,
                connection=conn,
                entity_type="product",
                internal_id="prod_102",
                external_id="ext_shopify_5501",
            )


# =========================================================================
# 4. Domain Services Tests
# =========================================================================


class TestIntegrationServices:
    def test_create_and_update_connection_service(self, connector_setup: dict[str, Any]) -> None:
        org = connector_setup["org1"]
        user = connector_setup["user_admin"]

        conn = services.create_integration_connection(
            organization=org,
            name="Stripe Sandbox Gateway",
            connector_type="fake_payments",
            config={"currency": "USD", "auto_capture": True},
            credentials={"api_key": "sk_test_123"},
            description="Main payment processor",
            actor=user,
        )
        assert conn.pk is not None
        assert conn.public_id is not None
        assert conn.credentials["api_key"] == "sk_test_123"

        # Update service
        updated = services.update_integration_connection(
            connection=conn,
            name="Stripe Sandbox Gateway (Updated)",
            sync_interval_minutes=30,
            actor=user,
        )
        assert updated.name == "Stripe Sandbox Gateway (Updated)"
        assert updated.sync_interval_minutes == 30

    def test_test_and_sync_services(self, connector_setup: dict[str, Any]) -> None:
        org = connector_setup["org1"]
        user = connector_setup["user_admin"]

        conn = services.create_integration_connection(
            organization=org,
            name="Generic API Feed",
            connector_type="generic_rest",
            config={"base_url": "https://api.myfeed.com", "auth_type": "none"},
            actor=user,
        )

        # Test connection
        res = services.test_integration_connection(connection=conn, actor=user)
        assert res.success is True

        # Run sync
        log, res_sync = services.run_integration_sync(
            connection=conn,
            direction="inbound",
            actor=user,
        )
        assert res_sync.success is True
        assert log.status == SyncStatus.SUCCESS
        assert log.records_processed > 0
        assert conn.last_synced_at is not None

    def test_external_reference_services(self, connector_setup: dict[str, Any]) -> None:
        org = connector_setup["org1"]
        user = connector_setup["user_admin"]

        conn = services.create_integration_connection(
            organization=org,
            name="Inventory Sync",
            connector_type="generic_rest",
            config={"base_url": "https://api.inventory.com"},
            actor=user,
        )

        ref = services.create_or_update_external_reference(
            organization=org,
            connection=conn,
            entity_type="product",
            internal_id="item_alpha_1",
            external_id="sku_ext_999",
            metadata={"source": "external_api"},
            actor=user,
        )
        assert ref.pk is not None

        # Lookup
        found = selectors.get_external_reference(
            org,
            connection=conn,
            entity_type="product",
            external_id="sku_ext_999",
        )
        assert found is not None
        assert found.internal_id == "item_alpha_1"

        # Update through service
        services.create_or_update_external_reference(
            organization=org,
            connection=conn,
            entity_type="product",
            internal_id="item_alpha_1_renamed",
            external_id="sku_ext_999",
            metadata={"source": "external_api", "updated": True},
            actor=user,
        )
        found.refresh_from_db()
        assert found.internal_id == "item_alpha_1_renamed"

        # Delete
        services.delete_external_reference(reference=found, actor=user)
        assert (
            selectors.get_external_reference(
                org,
                connection=conn,
                entity_type="product",
                external_id="sku_ext_999",
            )
            is None
        )

    def test_zapier_subscribe_and_unsubscribe_service(self, connector_setup: dict[str, Any]) -> None:
        org = connector_setup["org1"]
        user = connector_setup["user_admin"]

        conn = services.create_integration_connection(
            organization=org,
            name="Zapier Service",
            connector_type="zapier_compat",
            config={"api_key": "zap_123"},
            actor=user,
        )

        target_url = "https://hooks.zapier.com/hooks/catch/999/xyz"
        endpoint, hook_data = services.zapier_subscribe_hook(
            organization=org,
            connection=conn,
            event_type="invoice.paid",
            target_url=target_url,
            actor=user,
        )
        assert endpoint.is_active is True
        assert endpoint.url == target_url
        hook_id = hook_data["id"]

        # Verify backing external reference exists
        ref = selectors.get_external_reference(
            org,
            connection=conn,
            entity_type="zapier_hook",
            external_id=hook_id,
        )
        assert ref is not None

        # Unsubscribe
        ok = services.zapier_unsubscribe_hook(
            organization=org,
            connection=conn,
            hook_id=hook_id,
            actor=user,
        )
        assert ok is True
        endpoint.refresh_from_db()
        assert endpoint.is_active is False


# =========================================================================
# 5. Background Tasks Tests
# =========================================================================


class TestIntegrationTasks:
    def test_sync_integration_connection_task(self, connector_setup: dict[str, Any]) -> None:
        org = connector_setup["org1"]
        conn = services.create_integration_connection(
            organization=org,
            name="Scheduled Task Sync",
            connector_type="generic_rest",
            config={"base_url": "https://api.scheduled.com"},
        )
        res_str = tasks.sync_integration_connection_task(str(conn.public_id))
        assert "completed: success" in res_str.lower()
        conn.refresh_from_db()
        assert conn.last_synced_at is not None

    def test_sync_due_integration_connections_task(self, connector_setup: dict[str, Any]) -> None:
        org = connector_setup["org1"]
        # Create connection that has never been synced
        conn = services.create_integration_connection(
            organization=org,
            name="Due Sync Connection",
            connector_type="generic_rest",
            config={"base_url": "https://api.due.com"},
            sync_interval_minutes=15,
        )
        assert conn.last_synced_at is None

        # Run task
        triggered = tasks.sync_due_integration_connections_task()
        assert triggered >= 1


# =========================================================================
# 6. Web Views & HTMX Tests
# =========================================================================


class TestConnectorWebViews:
    def test_connections_list_view(self, connector_setup: dict[str, Any], client: Any) -> None:
        org = connector_setup["org1"]
        client.force_login(connector_setup["user_admin"])

        services.create_integration_connection(
            organization=org,
            name="Active Rest Store",
            connector_type="generic_rest",
            config={"base_url": "https://api.store.com"},
        )

        url = reverse("integrations:connections_list")
        resp = client.get(url, HTTP_X_ORGANIZATION_ID=str(org.public_id))
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Active Rest Store" in content
        assert "External Connectors" in content
        assert "Generic REST API" in content

    def test_connection_create_and_edit_view(self, connector_setup: dict[str, Any], client: Any) -> None:
        org = connector_setup["org1"]
        client.force_login(connector_setup["user_admin"])

        # GET create form
        url_create = reverse(
            "integrations:connection_create_typed",
            kwargs={"connector_type": "fake_payments"},
        )
        resp_get = client.get(url_create, HTTP_X_ORGANIZATION_ID=str(org.public_id))
        assert resp_get.status_code == 200

        # POST create
        post_data = {
            "name": "Web Form Payments",
            "connector_type": "fake_payments",
            "status": "active",
            "sync_interval_minutes": 45,
            "description": "Created from web form test",
            "config_json": json.dumps({"currency": "USD"}),
            "credentials_json": json.dumps({"api_key": "sec_test_web"}),
        }
        resp_post = client.post(
            reverse("integrations:connection_create"),
            post_data,
            HTTP_X_ORGANIZATION_ID=str(org.public_id),
        )
        assert resp_post.status_code == 302
        conn = IntegrationConnection.all_tenants.filter(organization=org, name="Web Form Payments").first()
        assert conn is not None
        assert conn.credentials["api_key"] == "sec_test_web"

        # Edit form
        url_edit = reverse("integrations:connection_edit", kwargs={"connection_id": conn.public_id})
        resp_edit_get = client.get(url_edit, HTTP_X_ORGANIZATION_ID=str(org.public_id))
        assert resp_edit_get.status_code == 200

    def test_connection_htmx_test_and_sync(self, connector_setup: dict[str, Any], client: Any) -> None:
        org = connector_setup["org1"]
        client.force_login(connector_setup["user_admin"])

        conn = services.create_integration_connection(
            organization=org,
            name="HTMX Test Connection",
            connector_type="generic_rest",
            config={"base_url": "https://api.htmx.com"},
        )

        # HTMX Test
        url_test = reverse("integrations:connection_test", kwargs={"connection_id": conn.public_id})
        resp_test = client.post(
            url_test,
            HTTP_HX_REQUEST="true",
            HTTP_X_ORGANIZATION_ID=str(org.public_id),
        )
        assert resp_test.status_code == 200
        assert "Connection Successful" in resp_test.content.decode()

        # HTMX Sync
        url_sync = reverse("integrations:connection_sync", kwargs={"connection_id": conn.public_id})
        resp_sync = client.post(
            url_sync,
            {"direction": "inbound"},
            HTTP_HX_REQUEST="true",
            HTTP_X_ORGANIZATION_ID=str(org.public_id),
        )
        assert resp_sync.status_code == 200
        assert "Sync Completed Successfully" in resp_sync.content.decode()


# =========================================================================
# 7. REST API Endpoints Tests
# =========================================================================


class TestConnectorAPI:
    def test_connection_api_crud_and_actions(self, connector_setup: dict[str, Any]) -> None:
        client = APIClient()
        client.force_authenticate(connector_setup["user_admin"])
        org = connector_setup["org1"]

        # 1. Create connection
        url_list = "/api/v1/integrations/connections/"
        payload = {
            "name": "API Created Connector",
            "connector_type": "generic_rest",
            "status": "active",
            "config": {"base_url": "https://api.vendor.com"},
            "credentials": {"api_key": "sec_vendor_token_123"},
        }
        res_create = client.post(
            url_list,
            payload,
            format="json",
            HTTP_X_ORGANIZATION_ID=str(org.public_id),
        )
        assert res_create.status_code == status.HTTP_201_CREATED
        pub_id = res_create.data["id"]

        # Verify credentials were not returned in response
        assert "credentials" not in res_create.data
        assert res_create.data["has_credentials"] is True

        # 2. Test action
        url_test = f"/api/v1/integrations/connections/{pub_id}/test/"
        res_test = client.post(url_test, {}, format="json", HTTP_X_ORGANIZATION_ID=str(org.public_id))
        assert res_test.status_code == status.HTTP_200_OK
        assert res_test.data["success"] is True

        # 3. Sync action
        url_sync = f"/api/v1/integrations/connections/{pub_id}/sync/"
        res_sync = client.post(
            url_sync,
            {"direction": "inbound"},
            format="json",
            HTTP_X_ORGANIZATION_ID=str(org.public_id),
        )
        assert res_sync.status_code == status.HTTP_200_OK
        assert res_sync.data["success"] is True
        assert res_sync.data["status"] == "success"

        # 4. Discrete action execute
        url_exec = f"/api/v1/integrations/connections/{pub_id}/execute/"
        res_exec = client.post(
            url_exec,
            {"action": "ping"},
            format="json",
            HTTP_X_ORGANIZATION_ID=str(org.public_id),
        )
        assert res_exec.status_code == status.HTTP_200_OK
        assert res_exec.data["success"] is True

    def test_zapier_endpoints(self, connector_setup: dict[str, Any]) -> None:
        client = APIClient()
        client.force_authenticate(connector_setup["user_admin"])
        org = connector_setup["org1"]

        # 1. Subscribe
        url_sub = "/api/v1/integrations/zapier/hooks/"
        sub_payload = {
            "target_url": "https://hooks.zapier.com/hooks/catch/777/abc",
            "event": "customer.created",
        }
        res_sub = client.post(
            url_sub,
            sub_payload,
            format="json",
            HTTP_X_ORGANIZATION_ID=str(org.public_id),
        )
        assert res_sub.status_code == status.HTTP_201_CREATED
        hook_id = res_sub.data["id"]

        # 2. Get Sample
        url_sample = "/api/v1/integrations/zapier/sample/customer.created/"
        res_sample = client.get(url_sample, HTTP_X_ORGANIZATION_ID=str(org.public_id))
        assert res_sample.status_code == status.HTTP_200_OK
        assert "name" in res_sample.data

        # 3. Unsubscribe
        res_unsub = client.delete(f"{url_sub}?id={hook_id}", HTTP_X_ORGANIZATION_ID=str(org.public_id))
        assert res_unsub.status_code == status.HTTP_204_NO_CONTENT


# =========================================================================
# 8. Cross-Tenant Isolation Tests
# =========================================================================


class TestTenantIsolation:
    def test_cross_tenant_connection_isolation(self, connector_setup: dict[str, Any]) -> None:
        org1 = connector_setup["org1"]
        org2 = connector_setup["org2"]

        conn1 = services.create_integration_connection(
            organization=org1,
            name="Org1 Private Connection",
            connector_type="generic_rest",
            config={"base_url": "https://api.org1.com"},
        )

        # Querying with Org2 tenant scope must return nothing
        with tenant_context(org2):
            conns_org2 = list(selectors.list_integration_connections(org2))
            assert not any(c.public_id == conn1.public_id for c in conns_org2)
            assert selectors.get_integration_connection(org2, connection_id=conn1.public_id) is None

        # API isolation: user in Org2 accessing Org1 connection -> 404
        client = APIClient()
        client.force_authenticate(connector_setup["user_org2"])
        url = f"/api/v1/integrations/connections/{conn1.public_id}/"
        res = client.get(url, HTTP_X_ORGANIZATION_ID=str(org2.public_id))
        assert res.status_code == status.HTTP_404_NOT_FOUND

    def test_permission_enforcement(self, connector_setup: dict[str, Any]) -> None:
        client = APIClient()
        org1 = connector_setup["org1"]

        # User viewer only has integrations.view, NOT integrations.manage
        client.force_authenticate(connector_setup["user_viewer"])
        url_create = "/api/v1/integrations/connections/"
        payload = {
            "name": "Unauthorized Connector",
            "connector_type": "generic_rest",
        }
        res_denied = client.post(
            url_create,
            payload,
            format="json",
            HTTP_X_ORGANIZATION_ID=str(org1.public_id),
        )
        assert res_denied.status_code == status.HTTP_403_FORBIDDEN
