"""URL configuration for the Sales and Invoicing module."""

from django.urls import path

from apps.sales import views

app_name = "sales"

urlpatterns = [
    # Quotes
    path("", views.invoice_list, name="index"),
    path("quotes/", views.quote_list, name="quote_list"),
    path("quotes/create/", views.quote_create, name="quote_create"),
    path("quotes/<uuid:public_id>/", views.quote_detail, name="quote_detail"),
    path("quotes/<uuid:public_id>/accept/", views.quote_accept, name="quote_accept"),
    path("quotes/<uuid:public_id>/convert/", views.quote_convert, name="quote_convert"),
    path("quotes/<uuid:public_id>/print/", views.quote_print, name="quote_print"),
    # Sales Orders
    path("orders/", views.order_list, name="order_list"),
    path("orders/create/", views.order_create, name="order_create"),
    path("orders/<uuid:public_id>/", views.order_detail, name="order_detail"),
    path("orders/<uuid:public_id>/confirm/", views.order_confirm, name="order_confirm"),
    path("orders/<uuid:public_id>/cancel/", views.order_cancel, name="order_cancel"),
    path("orders/<uuid:public_id>/invoice/", views.order_convert_to_invoice, name="order_convert_to_invoice"),
    # Invoices
    path("invoices/", views.invoice_list, name="invoice_list"),
    path("invoices/create/", views.invoice_create, name="invoice_create"),
    path("invoices/<uuid:public_id>/", views.invoice_detail, name="invoice_detail"),
    path("invoices/<uuid:public_id>/post/", views.invoice_post, name="invoice_post"),
    path("invoices/<uuid:public_id>/void/", views.invoice_void, name="invoice_void"),
    path("invoices/<uuid:public_id>/print/", views.invoice_print, name="invoice_print"),
    path(
        "invoices/<uuid:invoice_public_id>/credit-note/",
        views.credit_note_from_invoice,
        name="credit_note_from_invoice",
    ),
    # Credit Notes
    path("credit-notes/", views.credit_note_list, name="credit_note_list"),
    path("credit-notes/create/", views.credit_note_create, name="credit_note_create"),
    path("credit-notes/<uuid:public_id>/", views.credit_note_detail, name="credit_note_detail"),
    path("credit-notes/<uuid:public_id>/post/", views.credit_note_post, name="credit_note_post"),
    # Customer Payments
    path("payments/", views.payment_list, name="payment_list"),
    path("payments/create/", views.payment_create, name="payment_create"),
    path("payments/<uuid:public_id>/", views.payment_detail, name="payment_detail"),
    path("payments/<uuid:public_id>/allocate/", views.payment_allocate, name="payment_allocate"),
    path("payments/<uuid:public_id>/refund/", views.payment_refund, name="payment_refund"),
    path("payments/<uuid:public_id>/void/", views.payment_void, name="payment_void"),
    path("payments/<uuid:public_id>/receipt/", views.payment_receipt, name="payment_receipt"),
]
