"""POS Views package, split by domain use cases according to AGENTS.md rules."""

from __future__ import annotations

from apps.pos.views.common import _get_org
from apps.pos.views.hardware import (
    _extract_printer_name,
    open_drawer_action,
    printers_view,
    scanners_view,
    test_printer_action,
)
from apps.pos.views.registers import (
    register_create_view,
    register_list_view,
)
from apps.pos.views.shifts import (
    shift_close_view,
    shift_detail_view,
    shift_list_view,
    shift_open_view,
)
from apps.pos.views.terminal import (
    _parse_cart_lines,
    _parse_tenders,
    checkout_action,
    hold_cart_action,
    product_lookup_view,
    receipt_view,
    resume_cart_action,
    terminal_view,
)

__all__ = [
    "_extract_printer_name",
    "_get_org",
    "_parse_cart_lines",
    "_parse_tenders",
    "checkout_action",
    "hold_cart_action",
    "open_drawer_action",
    "printers_view",
    "product_lookup_view",
    "receipt_view",
    "register_create_view",
    "register_list_view",
    "resume_cart_action",
    "scanners_view",
    "shift_close_view",
    "shift_detail_view",
    "shift_list_view",
    "shift_open_view",
    "terminal_view",
    "test_printer_action",
]

