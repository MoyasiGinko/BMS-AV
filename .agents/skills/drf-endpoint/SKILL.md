---
name: drf-endpoint
description: Add a REST API resource under /api/v1/ with tenant scoping, permissions, filtering, pagination, idempotency and OpenAPI docs.
---
# DRF endpoint recipe

```python
# apps/sales/api/views.py
class InvoiceViewSet(TenantScopedViewSet):
    module_key = "sales"
    permission_map = {"list": "sales.view", "retrieve": "sales.view", "create": "sales.create", "confirm": "sales.confirm"}
    queryset = selectors.invoices()                  # already scoped + select_related
    serializer_class = InvoiceSerializer
    filterset_class = InvoiceFilter
    ordering_fields = ["date", "total"]
    search_fields = ["number", "customer__name"]

    def perform_create(self, serializer):
        serializer.instance = services.create_invoice(actor=self.request.user, **serializer.validated_data)

    @extend_schema(request=None, responses=InvoiceSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def confirm(self, request, pk=None):
        return Response(InvoiceSerializer(services.confirm_sale(sale_id=self.get_object().sale_id, actor=request.user)).data)
```
- Serializers: `public_id` exposed as `id`; read-only computed totals; no business rules.
- Register the router in `apps/<name>/api/urls.py` and include it in `config/api_urls.py` under `/api/v1/<name>/`.
- Tests (`apps/<name>/tests/test_api_<resource>.py`): auth required, entitlement, role denied, cross-tenant 404, pagination, filters,
  idempotent replay, error body format, query count.
- `python manage.py spectacular --validate --fail-on-warn` must pass.
