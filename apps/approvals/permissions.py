from apps.core.permissions import register_permission

PERMISSIONS = {
    "approvals.view": "View approvals inbox and historical requests",
    "approvals.approve": "Approve or reject submitted requests",
    "approvals.manage": "Configure approval rules and thresholds",
}

for code, desc in PERMISSIONS.items():
    register_permission(code, description=desc, module="approvals")
