import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client
from django.urls import reverse

User = get_user_model()
TEST_PASSWORD = "ValidPassword123!"


@pytest.mark.django_db
def test_login_screen_renders(client: Client) -> None:
    response = client.get(reverse("account_login"))
    assert response.status_code == 200
    assert "Sign in" in response.content.decode("utf-8")
    assert 'name="login"' in response.content.decode("utf-8")
    assert 'name="password"' in response.content.decode("utf-8")


@pytest.mark.django_db
def test_login_success(client: Client) -> None:
    user = User.objects.create_user(email="user@test.com", password=TEST_PASSWORD)
    response = client.post(
        reverse("account_login"),
        {"login": "user@test.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 302
    assert response.url == "/"
    assert "_auth_user_id" in client.session
    assert client.session["_auth_user_id"] == str(user.pk)


@pytest.mark.django_db
def test_login_invalid_credentials(client: Client) -> None:
    User.objects.create_user(email="user@test.com", password=TEST_PASSWORD)
    response = client.post(
        reverse("account_login"),
        {"login": "user@test.com", "password": "WrongPassword!"},
    )
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert (
        "The email address and/or password you specified are not correct" in content
        or "error" in content.lower()
    )
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_logout_flow(client: Client) -> None:
    User.objects.create_user(email="user@test.com", password=TEST_PASSWORD)
    client.login(email="user@test.com", password=TEST_PASSWORD)
    assert "_auth_user_id" in client.session

    response = client.post(reverse("account_logout"))
    assert response.status_code == 302
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_password_reset_flow(client: Client) -> None:
    User.objects.create_user(email="user@test.com", password=TEST_PASSWORD)

    # 1. Request password reset
    response = client.get(reverse("account_reset_password"))
    assert response.status_code == 200

    response = client.post(reverse("account_reset_password"), {"email": "user@test.com"})
    assert response.status_code == 302
    assert response.url == reverse("account_reset_password_done")

    # Verify reset email was sent via MAILERS locmem backend
    assert len(mail.outbox) == 1
    assert "password" in mail.outbox[0].subject.lower()


@pytest.mark.django_db
def test_email_verification_sent_screen(client: Client) -> None:
    response = client.get(reverse("account_email_verification_sent"))
    assert response.status_code == 200
    assert "Verify your email" in response.content.decode("utf-8")
