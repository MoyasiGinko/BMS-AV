"""Permissions definitions and registration for integrations and import/export."""

from __future__ import annotations

from apps.core.permissions import register_permission

PERMISSIONS = {
    "integrations.view": "View imports, exports, and integrations directory",
    "integrations.import": "Upload, validate, and commit data imports",
    "integrations.export": "Generate and download entity data exports",
    "integrations.manage": "Manage API keys, webhooks, and connector integrations",
}

for code, description in PERMISSIONS.items():
    register_permission(code, description=description, module="integrations")
