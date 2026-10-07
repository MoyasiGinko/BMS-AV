import pytest
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory

from apps.accounts.models import User
from apps.core.middleware import TenantMiddleware
from apps.tenancy.models import Organization


def dummy_view(request):
    return HttpResponse("OK")


@pytest.mark.django_db
def test_subdomain_resolution():
    org = Organization.objects.create(name="Subdomain Tenant", slug="subtenant")
    rf = RequestFactory()
    request = rf.get("/dashboard/", HTTP_HOST="subtenant.localhost")
    request.user = AnonymousUser()

    middleware = TenantMiddleware(dummy_view)
    response = middleware(request)

    assert request.organization == org
    assert response.status_code == 200


@pytest.mark.django_db
def test_exempt_path_without_tenant():
    rf = RequestFactory()
    request = rf.get("/healthz", HTTP_HOST="localhost")
    request.user = AnonymousUser()

    middleware = TenantMiddleware(dummy_view)
    response = middleware(request)

    assert request.organization is None
    assert response.status_code == 200


@pytest.mark.django_db
def test_protected_path_unauthenticated_redirects():
    rf = RequestFactory()
    request = rf.get("/protected-resource/", HTTP_HOST="localhost")
    request.user = AnonymousUser()

    middleware = TenantMiddleware(dummy_view)
    response = middleware(request)

    # Unauthenticated user redirected to login
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_session_fallback_resolution():
    org = Organization.objects.create(name="Session Tenant", slug="session-tenant")
    user = User.objects.create_user(email="session_user@example.com", password="val")
    rf = RequestFactory()
    request = rf.get("/dashboard/", HTTP_HOST="localhost")
    request.user = user
    request.session = {"active_org_id": org.pk}

    middleware = TenantMiddleware(dummy_view)
    response = middleware(request)

    assert request.organization == org
    assert response.status_code == 200
