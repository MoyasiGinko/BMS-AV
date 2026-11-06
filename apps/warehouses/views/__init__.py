"""Views package for the Warehouses and Locations module."""

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
    "branch_list_view",
    "location_list_view",
    "movement_ledger_view",
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
]
