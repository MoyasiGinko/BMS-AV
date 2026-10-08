"""REST API URL routing for the Sales and Invoicing module."""

from rest_framework.routers import DefaultRouter

from apps.sales.api import views

router = DefaultRouter()
router.register("quotes", views.QuoteViewSet, basename="quote")
router.register("orders", views.SalesOrderViewSet, basename="sales-order")
router.register("invoices", views.InvoiceViewSet, basename="invoice")
router.register("credit-notes", views.CreditNoteViewSet, basename="credit-note")
router.register("payments", views.PaymentViewSet, basename="payment")

urlpatterns = router.urls
