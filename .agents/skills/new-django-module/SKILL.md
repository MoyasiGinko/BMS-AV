---
name: new-django-module
description: Scaffold a new Django app module (models, services, selectors, events, permissions, API, views, templates, tests) following the platform conventions. Use at the start of every backlog task that introduces a module.
---
# New module scaffold

1. `mkdir -p apps/<name>/{api,templates/<name>,tests,migrations}`; add `__init__.py` files; create `apps.py` with `name = "apps.<name>"`, add to `INSTALLED_APPS`.
2. Register the module in `apps/billing/registry.py`: `ModuleRegistry.register(key="<name>", label=..., nav=[...], permissions=[...])`.
3. `models.py`:
```python
class Thing(TenantModel):
    public_id = models.UUIDField(default=uuid.uuid4, editable=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "code"], name="uniq_thing_org_code")]
        indexes = [models.Index(fields=["organization", "status", "-created_at"])]
```
4. `permissions.py`: `PERMISSIONS = {"<name>.view": ..., "<name>.create": ..., ...}`; seed into default roles in `apps/tenancy/roles.py`.
5. `services.py`: keyword-only functions with `actor`, `@transaction.atomic`, call `events.publish(...)`.
6. `selectors.py`: read-only querysets with `select_related`.
7. `events.py`: dataclass events (`ThingCreated`) + register handlers in `apps.py::ready()`.
8. `api/`: serializers (shape only), `TenantScopedViewSet`, filters, urls; register in `config/api_urls.py` (see skill `drf-endpoint`).
9. `views.py` + `urls.py` + templates built from `templates/components/` (see skill `htmx-screen`); add nav entry through the registry.
10. `admin.py` (read-mostly), `tasks.py` if background work exists.
11. `tests/`: factories in `tests/factories/<name>.py`; tests for services, API, permissions, isolation (see skill `tenant-isolation-test`).
12. `apps/<name>/README.md`: purpose, models, services, events, permissions, API endpoints.
13. Run `make verify`. Fix import-linter violations by moving code down a layer or using events.
