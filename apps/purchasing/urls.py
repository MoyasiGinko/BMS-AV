"""URL routing for Purchasing web views."""

from django.urls import path

from apps.purchasing import views

app_name = "purchasing"

urlpatterns = [
    # Suppliers
    path("suppliers/", views.supplier_list, name="supplier_list"),
    path("suppliers/new/", views.supplier_create, name="supplier_create"),
    path("suppliers/<int:pk>/", views.supplier_detail, name="supplier_detail"),
    path("suppliers/<int:pk>/edit/", views.supplier_update, name="supplier_update"),
    # Purchase Orders
    path("orders/", views.purchase_order_list, name="purchase_order_list"),
    path("orders/new/", views.purchase_order_create, name="purchase_order_create"),
    path("orders/<int:pk>/", views.purchase_order_detail, name="purchase_order_detail"),
    path("orders/<int:pk>/approve/", views.purchase_order_approve, name="purchase_order_approve"),
    path("orders/<int:pk>/cancel/", views.purchase_order_cancel, name="purchase_order_cancel"),
    # Goods Receipts
    path("receipts/", views.goods_receipt_list, name="goods_receipt_list"),
    path("receipts/<int:pk>/", views.goods_receipt_detail, name="goods_receipt_detail"),
    path("receipts/<int:pk>/receive/", views.goods_receipt_receive, name="goods_receipt_receive"),
    # Supplier Bills
    path("bills/", views.supplier_bill_list, name="supplier_bill_list"),
    path("bills/<int:pk>/", views.supplier_bill_detail, name="supplier_bill_detail"),
    path("bills/<int:pk>/post/", views.supplier_bill_post, name="supplier_bill_post"),
    path("bills/<int:pk>/void/", views.supplier_bill_void, name="supplier_bill_void"),
    # Supplier Payments
    path("payments/", views.supplier_payment_list, name="supplier_payment_list"),
    path("payments/new/", views.supplier_payment_create, name="supplier_payment_create"),
    path("payments/<int:pk>/", views.supplier_payment_detail, name="supplier_payment_detail"),
    # Purchase Returns
    path("returns/", views.purchase_return_list, name="purchase_return_list"),
    path("returns/<int:pk>/", views.purchase_return_detail, name="purchase_return_detail"),
    path("returns/<int:pk>/post/", views.purchase_return_post, name="purchase_return_post"),
]
