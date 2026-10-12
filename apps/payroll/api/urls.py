"""DRF API URL routes for Payroll module."""

from rest_framework.routers import DefaultRouter

from apps.payroll.api import views

app_name = "payroll_api"

router = DefaultRouter()
router.register("components", views.SalaryComponentViewSet, basename="component")
router.register("structures", views.SalaryStructureViewSet, basename="structure")
router.register("assignments", views.EmployeeSalaryAssignmentViewSet, basename="assignment")
router.register("runs", views.PayrollRunViewSet, basename="run")
router.register("payslips", views.PayslipViewSet, basename="payslip")

urlpatterns = router.urls
