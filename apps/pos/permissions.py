"""Permissions definition for the Point of Sale (POS) module."""

from apps.core.permissions import register_permission

PERMISSIONS = {
    "pos.access": "Access POS counter terminal and perform checkouts",
    "pos.checkout": "Process sales and split tender payments at the POS terminal",
    "pos.shift_open": "Open a cash register shift with opening cash float",
    "pos.shift_close": "Close a cash register shift, count cash, and record variance",
    "pos.manage": "Configure POS registers, adjust settings, and view all shift audits",
}


def register_pos_permissions() -> None:
    """Register POS permissions in the system permission catalog."""
    for code, desc in PERMISSIONS.items():
        register_permission(code, description=desc, module="pos")
