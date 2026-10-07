---
name: htmx-screen
description: Build a list/detail/form screen with Django templates, HTMX partials and the shared component library, following the design system.
---
# HTMX screen recipe

Files: `views.py`, `urls.py`, `forms.py`, `templates/<app>/<thing>_list.html` containing the full page AND its fragments as `{% partialdef table %}...{% endpartialdef %}` (Django template partials), plus `<thing>_form.html`, `<thing>_detail.html`.

```python
class ThingListView(TenantRequiredMixin, PermissionRequiredMixin, ListView):
    permission_code = "things.view"
    paginate_by = 25
    def get_queryset(self): return selectors.things(search=self.request.GET.get("q"), status=self.request.GET.get("status"))
    def get_template_names(self):
        return ["things/thing_list.html#table"] if self.request.htmx else ["things/thing_list.html"]
```
- Page skeleton: `{% extends "layouts/app.html" %}` -> `{% include "components/page_header.html" %}` -> filter bar (`hx-get`, `hx-trigger="input changed delay:300ms"`,
  `hx-target="#table"`, `hx-push-url="true"`) -> `components/data_table.html` -> pagination -> empty_state.
- Forms: render with `components/form_field.html`; on invalid return the form fragment with status 422; on success return `HX-Trigger: {"toast": {...}}` and either
  `HX-Redirect` or a refreshed fragment.
- Modals via `components/modal.html` loaded with `hx-get` into `#modal-root`.
- Add the nav entry through the module registry; add the screen to `/_styleguide/` only if you introduced a new component.
- Tests: view returns 200 for permitted role, 403 for denied role, fragment vs full-page rendering, validation error path, cross-tenant 404.
- UI smoke: add a Playwright test for the main flow of the module.
