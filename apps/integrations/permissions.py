"""Permissions definitions and registration for integrations and import/export."""

from __future__ import annotations

from apps.core.permissions import register_permission

PERMISSIONS = {
    "integrations.view": "View imports, exports, and integrations directory",
    "integrations.import": "Upload, validate, and commit data imports",
    "integrations.export": "Generate and download entity data exports",
    "integrations.manage": "Manage API keys, webhooks, and connector integrations",
    "integrations.sync": "Execute synchronization and test connector connections",
    "integrations.oauth_manage": "Register and configure OAuth applications",
    "integrations.inbound_manage": "Create and configure inbound webhook endpoints",
    "integrations.portability_manage": "Generate, download, and import full-tenant backup archives",
    "integrations.retention_manage": "Configure data retention policies and trigger log cleanup",
    "integrations.privacy_manage": "Process GDPR data subject access requests and erasure requests",
}

for code, description in PERMISSIONS.items():
    register_permission(code, description=description, module="integrations")
