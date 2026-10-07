"""Every API viewset must be tenant-scoped and permission-protected."""
def test_all_api_views_have_permissions():
    from django.urls import get_resolver
    from rest_framework.permissions import AllowAny
    bad = []
    def walk(patterns, prefix=""):
        for p in patterns:
            if hasattr(p, "url_patterns"):
                walk(p.url_patterns, prefix + str(p.pattern))
            else:
                cls = getattr(p.callback, "cls", None)
                if cls and str(prefix + str(p.pattern)).startswith("api/v1/"):
                    perms = getattr(cls, "permission_classes", [])
                    if any(x is AllowAny for x in perms) and not getattr(cls, "public_endpoint", False):
                        bad.append(cls.__name__)
    walk(get_resolver().url_patterns)
    assert not bad, f"Unprotected API views (set public_endpoint=True only for signup/health/webhooks-in): {bad}"
