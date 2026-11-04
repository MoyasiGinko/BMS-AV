"""Tests for SystemConfiguration, system deployment modes, and the First-Run Setup Wizard."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory, override_settings

from apps.core.middleware import TenantMiddleware
from apps.core.models import SystemConfiguration
from apps.core.setup.services import provision_initial_system
from apps.core.system_mode import (
    get_deployment_mode,
    get_primary_organization,
    is_dedicated_mode,
    is_saas_mode,
    is_system_initialized,
)
from apps.tenancy.models import Organization

User = get_user_model()


@pytest.mark.django_db
class TestSystemModeAndConfiguration:
    def test_default_system_configuration(self):
        config = SystemConfiguration.get_solo()
        assert config.pk == 1
        assert config.deployment_mode == SystemConfiguration.MODE_DEDICATED
        assert config.is_initialized is False

    def test_mode_helpers_reflect_configuration(self):
        config = SystemConfiguration.get_solo()
        config.deployment_mode = "dedicated"
        config.save()

        assert is_dedicated_mode() is True
        assert is_saas_mode() is False
        assert get_deployment_mode() == "dedicated"

        config.deployment_mode = "saas"
        config.save()

        assert is_dedicated_mode() is False
        assert is_saas_mode() is True
        assert get_deployment_mode() == "saas"

    @override_settings(DEPLOYMENT_MODE="dedicated")
    def test_settings_override_mode(self):
        assert is_dedicated_mode() is True
        assert is_saas_mode() is False

    @override_settings(DEPLOYMENT_MODE="saas")
    def test_settings_override_saas_mode(self):
        assert is_saas_mode() is True
        assert is_dedicated_mode() is False


@pytest.mark.django_db
class TestSetupProvisioningService:
    def test_provision_dedicated_mode(self):
        admin_user, org = provision_initial_system(
            deployment_mode="dedicated",
            system_name="Test Enterprise BMS",
            entity_name="Acme Corporation",
            admin_name="Lead Admin",
            admin_email="superadmin@testdomain.com",
            admin_password="SuperSecurePassword123!",
            country="BD",
            currency="BDT",
            timezone_str="Asia/Dhaka",
            fiscal_year_start=7,
            industry="retail",
            enabled_modules=["pos", "inventory", "sales", "accounting"],
        )

        assert admin_user is not None
        assert admin_user.is_superuser is True
        assert admin_user.email == "superadmin@testdomain.com"
        assert org is not None
        assert org.name == "Acme Corporation"
        assert org.base_currency == "BDT"

        config = SystemConfiguration.get_solo()
        assert config.is_initialized is True
        assert config.deployment_mode == "dedicated"
        assert config.primary_organization == org
        assert is_system_initialized() is True
        assert get_primary_organization() == org

    def test_provision_saas_mode(self):
        admin_user, org = provision_initial_system(
            deployment_mode="saas",
            system_name="SaaS Cloud BMS",
            entity_name="Cloud Platform",
            admin_name="Platform Owner",
            admin_email="owner@saasplatform.com",
            admin_password="SuperSecurePassword123!",
            country="US",
            currency="USD",
        )

        assert admin_user is not None
        assert admin_user.is_superuser is True
        config = SystemConfiguration.get_solo()
        assert config.is_initialized is True
        assert config.deployment_mode == "saas"
        assert config.allow_public_signup is True
        assert is_saas_mode() is True


@pytest.mark.django_db
class TestSetupMiddlewareAndRouting:
    def test_uninitialized_request_redirects_to_setup(self):
        config = SystemConfiguration.get_solo()
        config.is_initialized = False
        config.save()

        # Delete any existing organizations to simulate clean state
        Organization.objects.all().delete()

        rf = RequestFactory()
        request = rf.get("/dashboard/")
        request.session = {}

        middleware = TenantMiddleware(lambda req: None)
        response = middleware(request)

        assert response.status_code == 302
        assert response.url == "/setup/"

    def test_setup_url_exempt_from_redirect(self):
        config = SystemConfiguration.get_solo()
        config.is_initialized = False
        config.save()
        Organization.objects.all().delete()

        rf = RequestFactory()
        request = rf.get("/setup/")
        request.session = {}

        middleware = TenantMiddleware(lambda req: req)
        response = middleware(request)
        # Should not redirect away from /setup/
        assert response is request

    def test_dedicated_mode_auto_binds_primary_organization(self):
        admin_user, org = provision_initial_system(
            deployment_mode="dedicated",
            system_name="Dedicated Store",
            entity_name="Main Store",
            admin_name="Store Manager",
            admin_email="store@testbms.com",
            admin_password="PasswordSecure123!",
            country="BD",
            currency="BDT",
        )

        rf = RequestFactory()
        request = rf.get("/dashboard/")
        request.user = admin_user
        request.session = {}

        middleware = TenantMiddleware(lambda req: req)
        res = middleware(request)

        assert hasattr(request, "organization")
        assert request.organization == org
        assert request.tenant == org



@pytest.mark.django_db
class TestSetupWizardView:
    def test_get_wizard_when_uninitialized(self, client):
        config = SystemConfiguration.get_solo()
        config.is_initialized = False
        config.save()
        Organization.objects.all().delete()

        response = client.get("/setup/")
        assert response.status_code == 200
        assert "Choose deployment mode" in response.content.decode("utf-8")

    def test_post_wizard_initializes_system(self, client):
        config = SystemConfiguration.get_solo()
        config.is_initialized = False
        config.save()
        Organization.objects.all().delete()

        payload = {
            "deployment_mode": "dedicated",
            "system_name": "Wizard Test Store",
            "entity_name": "Wizard Corp",
            "admin_name": "Setup Admin",
            "admin_email": "setupadmin@teststore.com",
            "admin_password": "SecurePassword123!",
            "admin_password_confirm": "SecurePassword123!",
            "country": "BD",
            "currency": "BDT",
            "timezone": "Asia/Dhaka",
            "fiscal_year_start": "7",
            "industry": "retail",
            "modules": ["pos", "sales", "inventory"],
        }

        response = client.post("/setup/", data=payload)
        assert response.status_code == 302
        assert response.url == "/"

        # Verify system initialized
        config.refresh_from_db()
        assert config.is_initialized is True
        assert config.deployment_mode == "dedicated"
        assert config.primary_organization is not None
        assert config.primary_organization.name == "Wizard Corp"

    def test_wizard_redirects_when_already_initialized(self, client):
        config = SystemConfiguration.get_solo()
        config.is_initialized = True
        config.save()

        response = client.get("/setup/")
        assert response.status_code == 302
        assert response.url == "/"
