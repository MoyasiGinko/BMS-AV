"""Permissions and permission constants for the CRM module."""

from __future__ import annotations

from typing import Final

CRM_VIEW: Final[str] = "crm.view"
CRM_CREATE: Final[str] = "crm.create"
CRM_UPDATE: Final[str] = "crm.update"
CRM_DELETE: Final[str] = "crm.delete"
CRM_MANAGE: Final[str] = "crm.manage"
CRM_LEADS_CREATE: Final[str] = "crm.leads.create"
CRM_LEADS_EDIT: Final[str] = "crm.leads.edit"
CRM_LEADS_CONVERT: Final[str] = "crm.leads.convert"
CRM_OPPORTUNITIES_MANAGE: Final[str] = "crm.opportunities.manage"
CRM_ACTIVITIES_MANAGE: Final[str] = "crm.activities.manage"

ALL_CRM_PERMISSIONS: Final[list[str]] = [
    CRM_VIEW,
    CRM_CREATE,
    CRM_UPDATE,
    CRM_DELETE,
    CRM_MANAGE,
    CRM_LEADS_CREATE,
    CRM_LEADS_EDIT,
    CRM_LEADS_CONVERT,
    CRM_OPPORTUNITIES_MANAGE,
    CRM_ACTIVITIES_MANAGE,
]
