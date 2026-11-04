import json
import urllib.parse
from typing import Any

from django.apps import apps as django_apps
from django.http import HttpRequest

from apps.core.permissions import get_user_allowed_branch_ids
from apps.core.system_mode import (
    get_deployment_mode,
    is_dedicated_mode,
    is_system_initialized,
)

ALLOWED_THEMES = {"fast", "dark", "spatial", "neumorphic"}

THEME_SIDEBAR_PRESETS: dict[str, dict[str, dict[str, str]]] = {
    "fast": {
        "dark_contrast": {
            "name": "Dark Contrast (Default)",
            "bg": "#0f172a",
            "text": "#94a3b8",
            "hover_bg": "#1e293b",
            "hover_text": "#ffffff",
            "active_bg": "#134e4a",
            "active_text": "#2dd4bf",
            "active_border": "#14b8a6",
        },
        "light": {
            "name": "Clean White",
            "bg": "#ffffff",
            "text": "#475569",
            "hover_bg": "#f1f5f9",
            "hover_text": "#0f172a",
            "active_bg": "#f0fdfa",
            "active_text": "#0f766e",
            "active_border": "#0f766e",
        },
    },
    "dark": {
        "dark_contrast": {
            "name": "Midnight Dark (Default)",
            "bg": "#090d16",
            "text": "#94a3b8",
            "hover_bg": "#161f30",
            "hover_text": "#ffffff",
            "active_bg": "#1e293b",
            "active_text": "#2dd4bf",
            "active_border": "#14b8a6",
        },
        "light": {
            "name": "Elevated Surface",
            "bg": "#18233b",
            "text": "#cbd5e1",
            "hover_bg": "#223152",
            "hover_text": "#ffffff",
            "active_bg": "#111a2e",
            "active_text": "#2dd4bf",
            "active_border": "#2dd4bf",
        },
    },
    "spatial": {
        "dark_contrast": {
            "name": "Frosted Obsidian Glass (Default)",
            "bg": "rgba(15, 23, 42, 0.95)",
            "text": "#94a3b8",
            "hover_bg": "rgba(30, 41, 59, 0.90)",
            "hover_text": "#ffffff",
            "active_bg": "#1e3a5f",
            "active_text": "#38bdf8",
            "active_border": "#0284c7",
        },
        "light": {
            "name": "Frosted Opal Light Glass",
            "bg": "rgba(255, 255, 255, 0.90)",
            "text": "#334155",
            "hover_bg": "rgba(241, 245, 249, 0.90)",
            "hover_text": "#0f172a",
            "active_bg": "#e0f2fe",
            "active_text": "#0284c7",
            "active_border": "#0284c7",
        },
    },
    "neumorphic": {
        "light": {
            "name": "Soft Clay Light (Default)",
            "bg": "#e2e8f0",
            "text": "#334155",
            "hover_bg": "#cbd5e1",
            "hover_text": "#0f172a",
            "active_bg": "#dbeafe",
            "active_text": "#1d4ed8",
            "active_border": "#2563eb",
        },
        "dark_contrast": {
            "name": "Tactile Slate Dark",
            "bg": "#1e293b",
            "text": "#94a3b8",
            "hover_bg": "#334155",
            "hover_text": "#ffffff",
            "active_bg": "#0f172a",
            "active_text": "#60a5fa",
            "active_border": "#3b82f6",
        },
    },
}

DEFAULT_SIDEBAR_MODES: dict[str, str] = {
    "fast": "dark_contrast",
    "dark": "dark_contrast",
    "spatial": "dark_contrast",
    "neumorphic": "light",
}

DEFAULT_SIDEBAR_COLORS: dict[str, dict[str, str]] = {
    theme: presets[DEFAULT_SIDEBAR_MODES[theme]] for theme, presets in THEME_SIDEBAR_PRESETS.items()
}


def _resolve_active_theme(request: HttpRequest) -> str:
    """Resolve the active ground truth platform theme."""
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False) and getattr(user, "theme", None) in ALLOWED_THEMES:
        return user.theme
    cookie_theme = request.COOKIES.get("bos_theme")
    if cookie_theme in ALLOWED_THEMES:
        return cookie_theme
    org = getattr(request, "organization", None) or getattr(request, "tenant", None)
    if org and isinstance(getattr(org, "settings", None), dict):
        val = org.settings.get("default_theme", "fast")
        if val in ALLOWED_THEMES:
            return val
    return "fast"


def _extract_user_sidebar_modes(request: HttpRequest) -> dict[str, str]:
    """Extract per-theme sidebar modes from user model or cookies."""
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        cfg = getattr(user, "theme_config", None)
        if isinstance(cfg, dict) and isinstance(cfg.get("sidebar_modes"), dict):
            return {
                k: str(v)
                for k, v in cfg["sidebar_modes"].items()
                if k in ALLOWED_THEMES and v in ("dark_contrast", "light", "custom")
            }
    cookie_raw = request.COOKIES.get("bos_sidebar_modes", "")
    if cookie_raw:
        try:
            parsed = json.loads(urllib.parse.unquote(cookie_raw))
            if isinstance(parsed, dict):
                return {
                    k: str(v)
                    for k, v in parsed.items()
                    if k in ALLOWED_THEMES and v in ("dark_contrast", "light", "custom")
                }
        except json.JSONDecodeError, UnicodeDecodeError, ValueError:
            pass
    return {}


def _extract_user_sidebar_custom(
    request: HttpRequest,
) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    """Extract custom sidebar color dictionaries."""
    sidebar_custom: dict[str, dict[str, str]] = {}
    custom_single: dict[str, str] = {}
    valid_keys = ("bg", "text", "hover_bg", "hover_text", "active_bg", "active_text")

    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        cfg = getattr(user, "theme_config", None)
        if isinstance(cfg, dict):
            if isinstance(cfg.get("sidebar_custom"), dict):
                sidebar_custom = {
                    k: {ck: str(cv) for ck, cv in v.items() if ck in valid_keys}
                    for k, v in cfg["sidebar_custom"].items()
                    if k in ALLOWED_THEMES and isinstance(v, dict)
                }
            if isinstance(cfg.get("sidebar"), dict):
                custom_single = {k: str(v) for k, v in cfg["sidebar"].items() if k in valid_keys}

    if not custom_single:
        cookie_val = request.COOKIES.get("bos_sidebar_theme", "")
        if cookie_val:
            try:
                parsed = json.loads(urllib.parse.unquote(cookie_val))
                if isinstance(parsed, dict):
                    custom_single = {k: str(v) for k, v in parsed.items() if k in valid_keys}
            except json.JSONDecodeError, UnicodeDecodeError, ValueError:
                pass

    return sidebar_custom, custom_single


def _resolve_sidebar_for_theme(
    theme: str,
    modes: dict[str, str],
    customs: dict[str, dict[str, str]],
    custom_single: dict[str, str],
) -> tuple[str, dict[str, str]]:
    """Determine final mode and color map for the given theme."""

    presets = THEME_SIDEBAR_PRESETS.get(theme, THEME_SIDEBAR_PRESETS["fast"])

    default_mode = DEFAULT_SIDEBAR_MODES.get(theme, "dark_contrast")
    if theme in modes:
        mode = modes[theme]
    elif customs.get(theme) or (theme == "fast" and custom_single and not modes):
        mode = "custom"
    else:
        mode = default_mode

    if mode == "light":
        return "light", dict(presets["light"])
    if mode == "custom":
        res = dict(presets[default_mode])
        override = customs.get(theme) or (custom_single if (theme == "fast" and not modes) else {})
        res.update(override)
        return "custom", res
    return "dark_contrast", dict(presets["dark_contrast"])


def theme_context(request: HttpRequest) -> dict[str, Any]:
    """Provide current active theme for server-rendered <html data-theme="..."> tag."""
    theme = _resolve_active_theme(request)
    user_sidebar_modes = _extract_user_sidebar_modes(request)
    user_sidebar_custom, custom_sidebar = _extract_user_sidebar_custom(request)

    active_mode, active_sidebar_colors = _resolve_sidebar_for_theme(
        theme, user_sidebar_modes, user_sidebar_custom, custom_sidebar
    )

    bg_val = active_sidebar_colors.get("bg", "")
    is_light = bg_val in ("#ffffff", "#e2e8f0", "#f8fafc") or "255, 255, 255" in bg_val
    active_sidebar_tone = "light" if is_light else "dark"

    return {
        "current_theme": theme,
        "default_theme": "fast",
        "active_sidebar_mode": active_mode,
        "active_sidebar_colors": active_sidebar_colors,
        "active_sidebar_tone": active_sidebar_tone,
        "user_sidebar_modes": user_sidebar_modes,
        "user_sidebar_modes_json": json.dumps(user_sidebar_modes),
        "user_sidebar_custom": user_sidebar_custom,
        "user_sidebar_custom_json": json.dumps(user_sidebar_custom),
        "theme_sidebar_presets": THEME_SIDEBAR_PRESETS,
        "theme_sidebar_presets_json": json.dumps(THEME_SIDEBAR_PRESETS),
        "custom_sidebar": custom_sidebar,
        "custom_sidebar_json": json.dumps(active_sidebar_colors if active_mode == "custom" else {}),
        "available_themes": [
            {
                "id": "fast",
                "name": "Modern & Fast",
                "weight": "Lightweight (Default) • Best for performance",
                "description": "High contrast, crisp borders, and instant responsiveness.",
            },
            {
                "id": "dark",
                "name": "Modern Dark",
                "weight": "Dark Mode",
                "description": "Deep midnight slate palette for low-light environments.",
            },
            {
                "id": "spatial",
                "name": "Minimal Spatial",
                "weight": "Spatial Depth",
                "description": "Translucent frosted glass with clean spatial depth.",
            },
            {
                "id": "neumorphic",
                "name": "Neumorphic",
                "weight": "Tactile Surface",
                "description": "Soft tactile dual-shadow embossed surfaces.",
            },
        ],
    }


def deployment_context(request: HttpRequest) -> dict[str, Any]:
    """Provide deployment mode and system setup status to templates."""
    dedicated = is_dedicated_mode()
    return {
        "deployment_mode": get_deployment_mode(),
        "is_dedicated_mode": dedicated,
        "is_saas_mode": not dedicated,
        "system_initialized": is_system_initialized(),
    }


def branch_context(request: HttpRequest) -> dict[str, Any]:
    """Provide active branch and list of available branches for the active organization."""
    org = getattr(request, "organization", None) or getattr(request, "tenant", None)
    user = getattr(request, "user", None)
    if not org or not user or not getattr(user, "is_authenticated", False):
        return {
            "current_branch": None,
            "available_branches": [],
            "has_multiple_branches": False,
        }

    if not django_apps.is_installed("apps.tenancy"):
        return {
            "current_branch": None,
            "available_branches": [],
            "has_multiple_branches": False,
        }

    branch_model: Any = django_apps.get_app_config("tenancy").get_model("Branch")
    if branch_model is None:
        return {
            "current_branch": None,
            "available_branches": [],
            "has_multiple_branches": False,
        }

    allowed_ids = get_user_allowed_branch_ids(user, organization=org)
    qs = branch_model.all_tenants.filter(organization=org, is_active=True).order_by(
        "-is_headquarters", "name"
    )
    if allowed_ids is not None:
        qs = qs.filter(id__in=allowed_ids)

    branches = list(qs)
    current_branch = getattr(request, "branch", None)

    return {
        "current_branch": current_branch,
        "available_branches": branches,
        "has_multiple_branches": len(branches) > 1,
    }
