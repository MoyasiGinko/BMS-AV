import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.tenancy.models import Role
from apps.tenancy.services import create_organization, invite_member

User = get_user_model()
TEST_PASS = "SecretPassword123!"


@pytest.mark.django_db
def test_select_organization_multiple(client: Client) -> None:
    u = User.objects.create_user(email="user_m@test.com", password=TEST_PASS)
    create_organization(name="Workspace One", slug="w1", owner=u)
    create_organization(name="Workspace Two", slug="w2", owner=u)

    client.login(email="user_m@test.com", password=TEST_PASS)
    response = client.get(reverse("tenancy:select"))
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Workspace One" in content
    assert "Workspace Two" in content


@pytest.mark.django_db
def test_select_organization_single_redirects(client: Client) -> None:
    u = User.objects.create_user(email="user_s@test.com", password=TEST_PASS)
    create_organization(name="Only Workspace", slug="only-ws", owner=u)

    client.login(email="user_s@test.com", password=TEST_PASS)
    response = client.get(reverse("tenancy:select"))
    # Automatically selects single org and redirects
    assert response.status_code == 302
    assert response.url == "/"


@pytest.mark.django_db
def test_switch_organization_view(client: Client) -> None:
    u = User.objects.create_user(email="switcher@test.com", password=TEST_PASS)
    create_organization(name="First WS", slug="first-ws", owner=u)
    org2 = create_organization(name="Second WS", slug="second-ws", owner=u)

    client.login(email="switcher@test.com", password=TEST_PASS)
    response = client.get(reverse("tenancy:switch", kwargs={"organization_id": org2.pk}))
    assert response.status_code == 302
    assert client.session["active_org_id"] == org2.pk


@pytest.mark.django_db
def test_accept_invitation_view(client: Client) -> None:
    owner = User.objects.create_user(email="owner_v@test.com", password=TEST_PASS)
    org = create_organization(name="Invited Corp", slug="invited-corp", owner=owner)
    role = Role.all_tenants.filter(organization=org, name="Admin").first()
    assert role is not None

    invite = invite_member(organization=org, email="joiner@test.com", role=role, actor=owner)

    User.objects.create_user(email="joiner@test.com", password=TEST_PASS)
    client.login(email="joiner@test.com", password=TEST_PASS)

    # 1. GET invite page
    url = reverse("tenancy:accept_invitation", kwargs={"token": invite.token})
    response = client.get(url)
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Invited Corp" in content
    assert "Admin" in content

    # 2. POST accept
    post_res = client.post(url)
    assert post_res.status_code == 302
    assert post_res.url == "/"
    assert client.session["active_org_id"] == org.pk
