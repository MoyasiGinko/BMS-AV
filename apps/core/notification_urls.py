"""URLs for In-App Notifications Center and User Notification Preferences."""

from django.urls import path

from apps.core import notification_views

app_name = "notifications"

urlpatterns = [
    path("", notification_views.notification_center_view, name="center"),
    path("unread-count/", notification_views.notification_unread_count_view, name="unread_count"),
    path("preview/", notification_views.notification_preview_view, name="preview"),
    path("mark-all-read/", notification_views.notification_mark_all_read_view, name="mark_all_read"),
    path("preferences/", notification_views.user_notification_preferences_view, name="preferences"),
    path("<str:public_id>/read/", notification_views.notification_mark_read_view, name="mark_read"),
    path("<str:public_id>/unread/", notification_views.notification_mark_unread_view, name="mark_unread"),
    path("<str:public_id>/delete/", notification_views.notification_delete_view, name="delete"),
]
