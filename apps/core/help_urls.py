"""URL routes for the in-app Help Center."""

from django.urls import path

from apps.core import help_views

app_name = "help"

urlpatterns = [
    path("", help_views.help_index_view, name="index"),
    path("<slug:slug>/", help_views.help_article_view, name="article"),
    path("<slug:slug>/feedback/", help_views.help_feedback_view, name="feedback"),
]
