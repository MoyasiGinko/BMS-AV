"""Integration tests for CRM web views, Kanban board, and HTMX partials."""

from decimal import Decimal
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.crm import services
from apps.crm.models import LeadSource, LeadStatus, Stage
from apps.customers import services as customers_services
from apps.tenancy.models import Membership, Organization, Role


@pytest.fixture
def view_setup(db: None) -> dict[str, Any]:
    user = User.objects.create_user(email="crm_view_user@example.com", password="Password123!")
    org = Organization.objects.create(name="CRM Views Org", slug="crm-views-org")

    role = Role.objects.create(
        organization=org,
        name="CRM Full Admin",
        permissions=[
            "crm.view",
            "crm.create",
            "crm.update",
            "crm.delete",
            "crm.manage",
        ],
    )
    Membership.objects.create(
        organization=org,
        user=user,
        role=role,
        is_owner=True,
        status=Membership.STATUS_ACTIVE,
    )

    client = Client()
    client.force_login(user)

    pipeline = services.seed_default_pipeline(organization=org, actor=user)

    lead = services.create_lead(
        organization=org,
        first_name="Arthur",
        last_name="Dent",
        company_name="Betelgeuse Ltd",
        email="arthur@guide.galaxy",
        source=LeadSource.WEBSITE,
        status=LeadStatus.NEW,
        estimated_value=Decimal("4200.0000"),
        actor=user,
    )

    customer = customers_services.create_customer(
        organization=org,
        name="Sirius Cybernetics Corp",
        actor=user,
    )

    opp = services.create_opportunity(
        organization=org,
        title="GPP Elevator Deals",
        pipeline=pipeline,
        stage=Stage.all_tenants.filter(organization=org, pipeline=pipeline).first(),
        customer=customer,
        expected_value=Decimal("15000.0000"),
        actor=user,
    )

    return {
        "user": user,
        "org": org,
        "client": client,
        "pipeline": pipeline,
        "lead": lead,
        "customer": customer,
        "opp": opp,
    }


@pytest.mark.django_db
class TestCrmViews:
    def test_lead_list_view_and_htmx_partial(self, view_setup: dict[str, Any]) -> None:
        client: Client = view_setup["client"]
        url = reverse("crm:lead_list")

        # Full page
        response = client.get(url)
        assert response.status_code == 200
        assert "Arthur" in response.content.decode()

        # HTMX partial
        response_htmx = client.get(url, HTTP_HX_REQUEST="true")
        assert response_htmx.status_code == 200
        content = response_htmx.content.decode()
        assert "Arthur" in content
        assert "<html" not in content

    def test_lead_create_and_edit_views(self, view_setup: dict[str, Any]) -> None:
        client: Client = view_setup["client"]
        lead = view_setup["lead"]

        # Form GET
        create_url = reverse("crm:lead_create")
        res_get = client.get(create_url)
        assert res_get.status_code == 200

        # Create POST
        post_data = {
            "first_name": "Ford",
            "last_name": "Prefect",
            "company_name": "Sub-Etha Media",
            "email": "ford@guide.galaxy",
            "phone": "+12345",
            "title": "Field Researcher",
            "source": "website",
            "status": "new",
            "estimated_value": "9999.00",
            "tags_csv": "VIP, Outbound",
            "notes": "Always knows where his towel is.",
        }
        res_post = client.post(create_url, post_data)
        assert res_post.status_code == 302

        # Edit GET
        edit_url = reverse("crm:lead_edit", kwargs={"public_id": lead.public_id})
        res_edit = client.get(edit_url)
        assert res_edit.status_code == 200

    def test_lead_detail_and_convert_views(self, view_setup: dict[str, Any]) -> None:
        client: Client = view_setup["client"]
        lead = view_setup["lead"]

        detail_url = reverse("crm:lead_detail", kwargs={"public_id": lead.public_id})
        res_detail = client.get(detail_url)
        assert res_detail.status_code == 200
        assert "Arthur" in res_detail.content.decode()

        # Convert GET & POST
        convert_url = reverse("crm:lead_convert", kwargs={"public_id": lead.public_id})
        res_conv_get = client.get(convert_url)
        assert res_conv_get.status_code == 200

        res_conv_post = client.post(convert_url, {"create_opportunity": "on"})
        assert res_conv_post.status_code == 302
        lead.refresh_from_db()
        assert lead.status == LeadStatus.CONVERTED

    def test_pipeline_kanban_and_stage_move_htmx(self, view_setup: dict[str, Any]) -> None:
        client: Client = view_setup["client"]
        opp = view_setup["opp"]
        pipeline = view_setup["pipeline"]

        kanban_url = reverse("crm:pipeline_kanban")
        res_kanban = client.get(kanban_url)
        assert res_kanban.status_code == 200
        assert "GPP Elevator Deals" in res_kanban.content.decode()

        stages_qs = Stage.all_tenants.filter(organization=view_setup["org"], pipeline=pipeline).order_by(
            "order"
        )
        target_stage = list(stages_qs)[1]
        move_url = reverse(
            "crm:opportunity_stage_move",
            kwargs={"public_id": opp.public_id, "stage_id": target_stage.id},
        )
        res_move = client.post(move_url, HTTP_HX_REQUEST="true")
        assert res_move.status_code == 200
        assert "GPP Elevator Deals" in res_move.content.decode()
        opp.refresh_from_db()
        assert opp.stage == target_stage

    def test_customer_360_views(self, view_setup: dict[str, Any]) -> None:
        client: Client = view_setup["client"]
        customer = view_setup["customer"]

        # Index view
        res_index = client.get(reverse("crm:customer_360_index"))
        assert res_index.status_code == 200
        assert "Sirius Cybernetics Corp" in res_index.content.decode()

        # 360 overview
        c360_url = reverse("crm:customer_360", kwargs={"customer_id": customer.pk})
        res_360 = client.get(c360_url)
        assert res_360.status_code == 200
        assert "Sirius Cybernetics Corp" in res_360.content.decode()
        assert "GPP Elevator Deals" in res_360.content.decode()

    def test_inactive_customers_view(self, view_setup: dict[str, Any]) -> None:
        client: Client = view_setup["client"]
        url = reverse("crm:inactive_customers")
        res = client.get(url)
        assert res.status_code == 200

    def test_log_interaction_and_task_views_htmx(self, view_setup: dict[str, Any]) -> None:
        client: Client = view_setup["client"]
        lead = view_setup["lead"]
        org = view_setup["org"]
        user = view_setup["user"]

        # HTMX log interaction
        log_url = reverse("crm:log_interaction")
        res_log = client.post(
            log_url,
            {
                "lead_id": lead.pk,
                "type": "call",
                "summary": "Called prospect regarding quote",
                "details": "They seemed interested.",
            },
            HTTP_HX_REQUEST="true",
        )
        assert res_log.status_code == 200
        assert "Called prospect regarding quote" in res_log.content.decode()

        # Task toggle complete
        task = services.create_crm_task(
            organization=org,
            title="Send product spec",
            lead=lead,
            actor=user,
        )
        task_toggle_url = reverse("crm:task_toggle_complete", kwargs={"public_id": task.public_id})
        res_task = client.post(task_toggle_url, HTTP_HX_REQUEST="true")
        assert res_task.status_code == 200
        assert "Send product spec" in res_task.content.decode()
