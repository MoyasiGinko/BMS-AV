from __future__ import annotations

from typing import Any

from django.http import HttpRequest

ALLOWED_THEMES = {"fast", "dark", "spatial", "neumorphic"}


def theme_context(request: HttpRequest) -> dict[str, Any]:
    """Provide current active theme for server-rendered <html data-theme="..."> tag.

    Priority:
    1. Authenticated user's profile theme (request.user.theme) - primary ground truth
    2. Cookie 'bos_theme' (guest sessions and pre-login preferences)
    3. Tenant organization default theme (request.tenant.settings['default_theme'])
    4. Fallback to 'fast'
    """
    theme = "fast"
    if request.user.is_authenticated and getattr(request.user, "theme", None) in ALLOWED_THEMES:
        theme = request.user.theme
    elif request.COOKIES.get("bos_theme") in ALLOWED_THEMES:
        theme = request.COOKIES.get("bos_theme")
    else:
        org = getattr(request, "organization", None) or getattr(request, "tenant", None)
        if org and isinstance(getattr(org, "settings", None), dict):
            theme = org.settings.get("default_theme", "fast")

    if theme not in ALLOWED_THEMES:
        theme = "fast"

    return {
        "current_theme": theme,
        "default_theme": "fast",
        "available_themes": [
            {
                "id": "fast",
                "name": "Modern & Fast",
                "weight": "Lightweight (Default) • Best for performance & old devices",
                "description": "Crisp 1px borders, high contrast, zero blur, instant 60fps rendering.",
            },
            {
                "id": "dark",
                "name": "Modern Dark",
                "weight": "Lightweight • Deep dark palette for low-light environments",
                "description": ("Deep midnight slate palette with soft teal accents and low eye strain."),
            },
            {
                "id": "spatial",
                "name": "Minimal Spatial",
                "weight": "Balanced • Clean spatial depth & modern typography",
                "description": (
                    "Delicate floating elevations, translucent frosted glass headers, and spacious cards."
                ),
            },
            {
                "id": "neumorphic",
                "name": "Neumorphic",
                "weight": "Heavy • Tactile dual-shadow continuous surface",
                "description": (
                    "Single continuous surface with dual opposing 135° soft highlights & sunken wells."
                ),
            },
        ],
    }
