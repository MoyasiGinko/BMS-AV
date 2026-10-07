---
name: tenant-isolation-test
description: Write the mandatory cross-tenant isolation, permission and entitlement tests for any feature.
---
# Tenant isolation test template

```python
@pytest.mark.django_db
def test_cannot_access_other_org(api_client_factory, org_factory, thing_factory):
    a, b = org_factory(), org_factory()
    thing_b = thing_factory(organization=b)
    client = api_client_factory(org=a, role="owner")
    assert client.get(f"/api/v1/things/{thing_b.public_id}/").status_code == 404
    assert thing_b.public_id not in [r["id"] for r in client.get("/api/v1/things/").json()["results"]]
    assert client.patch(f"/api/v1/things/{thing_b.public_id}/", {"name": "x"}).status_code == 404
    assert client.delete(f"/api/v1/things/{thing_b.public_id}/").status_code == 404

@pytest.mark.django_db
def test_role_and_entitlement(api_client_factory, org_factory):
    org = org_factory(plan="starter_without_things")
    assert api_client_factory(org=org, role="owner").get("/api/v1/things/").status_code == 403   # plan
    org2 = org_factory(plan="full")
    assert api_client_factory(org=org2, role="viewer").post("/api/v1/things/", {...}).status_code == 403  # role
```
Also cover: exports, Celery task with wrong `organization_id`, web views, and RLS (raw query with `app.current_org` set to A returns no B rows).
