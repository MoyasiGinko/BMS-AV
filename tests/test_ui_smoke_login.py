import pytest
from django.contrib.auth import get_user_model
from playwright.sync_api import Page, expect

User = get_user_model()


@pytest.mark.ui
@pytest.mark.django_db(transaction=True)
def test_ui_smoke_login(live_server: pytest.FixtureRequest, page: Page) -> None:
    # 1. Seed user
    User.objects.create_user(
        email="smoke_user@example.com",
        password="SmokePassword123!",
        name="Smoke Tester",
    )

    # 2. Visit login page
    server_url = getattr(live_server, "url", str(live_server))
    page.goto(f"{server_url}/accounts/login/")

    # 3. Assert page elements render per Calm Ledger design
    expect(page.locator("h1")).to_have_text("Business OS")
    expect(page.locator("#id_login")).to_be_visible()
    expect(page.locator("#id_password")).to_be_visible()
    expect(page.locator("#submit-login-btn")).to_be_visible()

    # 4. Fill credentials and submit
    page.fill("#id_login", "smoke_user@example.com")
    page.fill("#id_password", "SmokePassword123!")
    page.click("#submit-login-btn")

    # 5. Successful login redirect (either to root "/" or tenancy selector)
    page.wait_for_load_state("networkidle")
    # Verify no login error was shown
    expect(
        page.locator("text=The email address and/or password you specified are not correct")
    ).not_to_be_visible()
