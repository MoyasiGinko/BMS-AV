"""URL patterns for tenancy module."""

from django.urls import path

from apps.tenancy.views import (
    accept_invitation_view,
    check_slug_view,
    onboarding_wizard_view,
    organization_list_view,
    select_organization_view,
    switch_branch_view,
    switch_organization_view,
)

app_name = "tenancy"

urlpatterns = [
    path("", organization_list_view, name="index"),
    path("list/", organization_list_view, name="organization_list"),
    path("onboarding/", onboarding_wizard_view, name="onboarding"),
    path("onboarding/check-slug/", check_slug_view, name="check_slug"),
    path("select/", select_organization_view, name="select"),
    path("switch/<int:organization_id>/", switch_organization_view, name="switch"),
    path("branches/switch/<str:branch_id>/", switch_branch_view, name="switch_branch"),
    path("branches/switch/", switch_branch_view, name="switch_branch_post"),
    path("invitations/<str:token>/accept/", accept_invitation_view, name="accept_invitation"),
]
