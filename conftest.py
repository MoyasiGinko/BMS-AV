"""Project-wide pytest fixtures. Factories live in tests/factories/."""

import os
import secrets

os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"

import pytest

from apps.accounts.models import User
from apps.billing.services import seed_default_plans
from apps.tenancy.models import Organization
from apps.tenancy.services import provision_organization


@pytest.fixture
def user(db: None) -> User:
    return User.objects.create_user(
        email="test_user@example.com",
        password=secrets.token_urlsafe(16),
    )


@pytest.fixture
def organization(db: None, user: User) -> Organization:
    seed_default_plans()
    return provision_organization(name="Test Org", slug="test-org", owner=user, plan="business")
