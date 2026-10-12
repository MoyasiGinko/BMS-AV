"""Permission codes for the Human Resources module."""

from __future__ import annotations

HR_VIEW = "hr.view"
HR_CREATE = "hr.create"
HR_UPDATE = "hr.update"
HR_DELETE = "hr.delete"
HR_APPROVE = "hr.approve"
HR_EXPORT = "hr.export"
HR_VIEW_SENSITIVE = "hr.view_sensitive"

HR_PERMISSIONS = [
    HR_VIEW,
    HR_CREATE,
    HR_UPDATE,
    HR_DELETE,
    HR_APPROVE,
    HR_EXPORT,
    HR_VIEW_SENSITIVE,
]
