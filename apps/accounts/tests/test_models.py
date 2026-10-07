import pytest

from apps.accounts.models import User

_TEST_INPUT = "sample_val_12345"


@pytest.mark.django_db
def test_create_user() -> None:
    user = User.objects.create_user(email="test@example.com", password=_TEST_INPUT, name="Test User")
    assert user.email == "test@example.com"
    assert user.check_password(_TEST_INPUT)
    assert not user.is_staff
    assert not user.is_superuser
    assert user.get_full_name() == "Test User"
    assert user.get_short_name() == "Test"
    assert str(user) == "test@example.com"


@pytest.mark.django_db
def test_create_user_empty_email() -> None:
    with pytest.raises(ValueError, match=r"An email address is required\."):
        User.objects.create_user(email="", password=_TEST_INPUT)


@pytest.mark.django_db
def test_create_superuser() -> None:
    user = User.objects.create_superuser(email="admin@example.com", password=_TEST_INPUT)
    assert user.email == "admin@example.com"
    assert user.is_staff
    assert user.is_superuser
    assert user.get_full_name() == "admin@example.com"
    assert user.get_short_name() == "admin@example.com"
