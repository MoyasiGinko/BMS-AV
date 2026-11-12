"""Views package for the Warehouses and Locations module."""

from apps.warehouses.views.adjustments import (
    adjustment_create_view,
    adjustment_detail_view,
    adjustment_list_view,
)
from apps.warehouses.views.dashboard import (
    warehouse_dashboard_view,
)
from apps.warehouses.views.facilities import (
    branch_list_view,
    warehouse_detail_view,
    warehouse_list_view,
)
from apps.warehouses.views.locations import (
    location_list_view,
    supply_route_list_view,
)
from apps.warehouses.views.movements import (
    movement_ledger_view,
)
from apps.warehouses.views.requests import (
    outlet_push_decision_view,
    warehouse_push_send_view,
    warehouse_request_detail_view,
    warehouse_request_list_view,
)
from apps.warehouses.views.stocking import (
    stock_intake_create_view,
    stock_intake_detail_view,
    stock_intake_list_view,
)
from apps.warehouses.views.transfers import (
    transfer_approve_view,
    transfer_cancel_view,
    transfer_create_view,
    transfer_detail_view,
    transfer_dispatch_view,
    transfer_list_view,
    transfer_receive_view,
    transfer_reject_view,
)

__all__ = [
    "adjustment_create_view",
    "adjustment_detail_view",
    "adjustment_list_view",
    "branch_list_view",
    "location_list_view",
    "movement_ledger_view",
    "outlet_push_decision_view",
    "stock_intake_create_view",
    "stock_intake_detail_view",
    "stock_intake_list_view",
    "supply_route_list_view",
    "transfer_approve_view",
    "transfer_cancel_view",
    "transfer_create_view",
    "transfer_detail_view",
    "transfer_dispatch_view",
    "transfer_list_view",
    "transfer_receive_view",
    "transfer_reject_view",
    "warehouse_dashboard_view",
    "warehouse_detail_view",
    "warehouse_list_view",
    "warehouse_push_send_view",
    "warehouse_request_detail_view",
    "warehouse_request_list_view",
]
