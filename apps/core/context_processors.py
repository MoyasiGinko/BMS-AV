import json
import urllib.parse
from typing import Any

from django.http import HttpRequest

ALLOWED_THEMES = {"fast", "dark", "spatial", "neumorphic"}

DEFAULT_SIDEBAR_COLORS: dict[str, dict[str, str]] = {
    "fast": {
        "bg": "#ffffff",
        "text": "#64748b",
        "hover_bg": "#f1f5f9",
        "hover_text": "#0f172a",
        "active_bg": "#f0fdfa",
        "active_text": "#0f766e",
    },
    "dark": {
        "bg": "#111a2e",
        "text": "#93a4c0",
        "hover_bg": "#18233b",
        "hover_text": "#ffffff",
        "active_bg": "#1e293b",
        "active_text": "#2dd4bf",
    },
    "spatial": {
        "bg": "rgba(255, 255, 255, 0.90)",
        "text": "#475569",
        "hover_bg": "rgba(241, 245, 249, 0.85)",
        "hover_text": "#0f172a",
        "active_bg": "#f0fdfa",
        "active_text": "#0f766e",
    },
    "neumorphic": {
        "bg": "#e2e8f0",
        "text": "#475569",
        "hover_bg": "#cbd5e1",
        "hover_text": "#0f172a",
        "active_bg": "#dbeafe",
        "active_text": "#1d4ed8",
    },
}


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

    # Sidebar customization extraction
    custom_sidebar: dict[str, str] = {}
    if request.user.is_authenticated:
        theme_cfg = getattr(request.user, "theme_config", None)
        if isinstance(theme_cfg, dict) and isinstance(theme_cfg.get("sidebar"), dict):
            custom_sidebar = {
                k: str(v)
                for k, v in theme_cfg["sidebar"].items()
                if k in ("bg", "text", "hover_bg", "hover_text", "active_bg", "active_text")
            }

    if not custom_sidebar:
        cookie_val = request.COOKIES.get("bos_sidebar_theme", "")
        if cookie_val:
            try:
                unquoted = urllib.parse.unquote(cookie_val)
                parsed = json.loads(unquoted)
                if isinstance(parsed, dict):
                    custom_sidebar = {
                        k: str(v)
                        for k, v in parsed.items()
                        if k in ("bg", "text", "hover_bg", "hover_text", "active_bg", "active_text")
                    }
            except json.JSONDecodeError, UnicodeDecodeError, ValueError:
                pass

    active_sidebar_colors = dict(DEFAULT_SIDEBAR_COLORS.get(theme, DEFAULT_SIDEBAR_COLORS["fast"]))
    active_sidebar_colors.update(custom_sidebar)

    return {
        "current_theme": theme,
        "default_theme": "fast",
        "custom_sidebar": custom_sidebar,
        "active_sidebar_colors": active_sidebar_colors,
        "custom_sidebar_json": json.dumps(custom_sidebar),
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
