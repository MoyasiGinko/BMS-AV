"""POS URL routing."""

from django.urls import path

from apps.pos import views

app_name = "pos"

urlpatterns = [
    path("", views.terminal_view, name="terminal"),
    path("checkout/", views.checkout_action, name="checkout"),
    path("receipt/<uuid:public_id>/", views.receipt_view, name="receipt"),
    path("shifts/", views.shift_list_view, name="shift_list"),
    path("shifts/open/", views.shift_open_view, name="shift_open"),
    path("shifts/<uuid:public_id>/", views.shift_detail_view, name="shift_detail"),
    path("shifts/<uuid:public_id>/close/", views.shift_close_view, name="shift_close"),
    path("registers/", views.register_list_view, name="register_list"),
    path("registers/new/", views.register_create_view, name="register_create"),
    path("cart/hold/", views.hold_cart_action, name="hold_cart"),
    path("cart/<int:held_cart_id>/resume/", views.resume_cart_action, name="resume_cart"),
    path("printers/", views.printers_view, name="printers"),
    path("scanners/", views.scanners_view, name="scanners"),
    path("printers/test/", views.test_printer_action, name="test_printer"),
    path("drawer/open/", views.open_drawer_action, name="open_drawer"),
]
