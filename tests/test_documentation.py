"""Automated test suite validating documentation completeness and in-app help center functionality."""

from pathlib import Path

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.tenancy.models import Membership, Organization, Role


@pytest.fixture
def auth_client() -> tuple[Client, User, Organization]:
    """Provide an authenticated Django test client bound to an active tenant."""
    org = Organization.objects.create(name="Doc Test Corp", slug="doc-test-corp")
    role = Role.objects.create(
        organization=org,
        name="Admin Role",
        permissions=["admin"],
    )
    user = User.objects.create_user(
        email="docuser@example.test",
        password="TestPassword123!",
    )
    Membership.objects.create(
        organization=org,
        user=user,
        role=role,
        status=Membership.STATUS_ACTIVE,
    )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(org.id)
    session.save()
    return client, user, org


@pytest.mark.django_db
class TestDocumentationCompleteness:
    """Validate repository-wide documentation assets."""

    REPO_ROOT = Path(__file__).resolve().parent.parent

    def test_root_readme_exists_and_complete(self) -> None:
        """Verify the root README.md exists and contains critical developer guides."""
        readme = self.REPO_ROOT / "README.md"
        assert readme.exists(), "Root README.md must exist."
        content = readme.read_text(encoding="utf-8")
        assert len(content) > 1000, "Root README.md must be comprehensive."
        assert "Business OS" in content
        assert "Quickstart" in content
        assert "make verify" in content
        assert "Architecture" in content
        assert "PostgreSQL 18" in content
        assert "Python 3.14" in content
        assert "Docker Compose" in content

    def test_all_apps_have_readmes(self) -> None:
        """Verify that every domain app in apps/ has an up-to-date README.md."""
        apps_dir = self.REPO_ROOT / "apps"
        app_subdirs = [
            d
            for d in apps_dir.iterdir()
            if d.is_dir() and not d.name.startswith("__") and (d / "__init__.py").exists()
        ]
        missing_readmes = []
        for app_dir in app_subdirs:
            readme = app_dir / "README.md"
            if not readme.exists() or len(readme.read_text(encoding="utf-8").strip()) < 50:
                missing_readmes.append(app_dir.name)

        assert not missing_readmes, f"Apps missing comprehensive README.md: {missing_readmes}"

    def test_api_guide_exists_and_complete(self) -> None:
        """Verify docs/API_GUIDE.md includes curl and Python examples across key domains."""
        api_guide = self.REPO_ROOT / "docs" / "API_GUIDE.md"
        assert api_guide.exists(), "docs/API_GUIDE.md must exist."
        content = api_guide.read_text(encoding="utf-8")
        assert "curl" in content
        assert "python" in content.lower()
        assert "X-API-Key" in content
        assert "Idempotency-Key" in content
        assert "/api/v1/sales/invoices/" in content
        assert "/api/v1/catalog/items/" in content
        assert "Retry-After" in content

    def test_integration_guide_exists_and_complete(self) -> None:
        """Verify docs/INTEGRATION_GUIDE.md documents webhooks, HMAC, and OAuth2."""
        guide = self.REPO_ROOT / "docs" / "INTEGRATION_GUIDE.md"
        assert guide.exists(), "docs/INTEGRATION_GUIDE.md must exist."
        content = guide.read_text(encoding="utf-8")
        assert "HMAC" in content
        assert "X-BOS-Signature" in content
        assert "OAuth 2.0" in content
        assert "PKCE" in content
        assert "Dead-Letter Queue" in content or "DLQ" in content
        assert "replay" in content.lower()

    def test_adr_0041_exists(self) -> None:
        """Verify ADR 0041 records architectural decisions for documentation."""
        adr = self.REPO_ROOT / "docs" / "adr" / "0041-documentation-and-developer-guides.md"
        assert adr.exists(), "ADR 0041 must exist."
        content = adr.read_text(encoding="utf-8")
        assert "ADR 0041" in content
        assert "Help Center" in content


@pytest.mark.django_db
class TestInAppHelpCenter:
    """Validate in-app interactive help center views and templates."""

    def test_help_index_renders_topics_and_faqs(self, auth_client) -> None:
        """Verify the help center landing page renders successfully."""
        client, _, _ = auth_client
        url = reverse("help:index")
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "Knowledge Base & User Manual" in content
        assert "Getting Started with Business OS" in content
        assert "Sales, Invoicing &amp; Receivables" in content
        assert "Frequently Asked Questions" in content
        assert "Keyboard Shortcuts" in content

    def test_help_search_htmx_partial(self, auth_client) -> None:
        """Verify live search filtering via HTMX returns matching topics partial."""
        client, _, _ = auth_client
        url = reverse("help:index") + "?q=invoice"
        response = client.get(url, HTTP_HX_REQUEST="true")
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "Sales, Invoicing &amp; Receivables" in content

    def test_help_article_view(self, auth_client) -> None:
        """Verify article detail view renders sections and table of contents."""
        client, _, _ = auth_client
        url = reverse("help:article", kwargs={"slug": "accounting-ledger"})
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "General Ledger &amp; Accounting" in content
        assert "Chart of Accounts &amp; Semantic Mappings" in content
        assert "Double-Entry Balance &amp; Immutability" in content
        assert "Was this article helpful?" in content

    def test_help_article_404(self, auth_client) -> None:
        """Verify non-existent topic returns 404."""
        client, _, _ = auth_client
        url = reverse("help:article", kwargs={"slug": "non-existent-module-xyz"})
        response = client.get(url)
        assert response.status_code == 404

    def test_help_feedback_submission(self, auth_client) -> None:
        """Verify submitting helpfulness feedback returns the thank you partial."""
        client, _, _ = auth_client
        url = reverse("help:feedback", kwargs={"slug": "sales-invoicing"})
        response = client.post(url, {"helpful": "yes"})
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "Thank you for your feedback!" in content
