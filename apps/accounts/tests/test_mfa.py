import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

User = get_user_model()
TEST_PASSWORD = "ValidPassword123!"


@pytest.mark.django_db
def test_mfa_requires_authentication(client: Client) -> None:
    response = client.get(reverse("mfa_index"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_mfa_index_authenticated(client: Client) -> None:
    User.objects.create_user(email="mfa_user@example.com", password=TEST_PASSWORD)
    client.login(email="mfa_user@example.com", password=TEST_PASSWORD)

    response = client.get(reverse("mfa_index"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_mfa_totp_activate_screen(client: Client) -> None:
    User.objects.create_user(email="mfa_user2@example.com", password=TEST_PASSWORD)
    client.post(reverse("account_login"), {"login": "mfa_user2@example.com", "password": TEST_PASSWORD})

    response = client.get(reverse("mfa_activate_totp"))
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "two-factor authentication" in content.lower()
    assert 'name="code"' in content
