"""URL patterns for tenancy module."""

from django.urls import path

from apps.tenancy.views import (
    accept_invitation_view,
    select_organization_view,
    switch_organization_view,
)

app_name = "tenancy"

urlpatterns = [
    path("select/", select_organization_view, name="select"),
    path("switch/<int:organization_id>/", switch_organization_view, name="switch"),
    path("invitations/<str:token>/accept/", accept_invitation_view, name="accept_invitation"),
]
