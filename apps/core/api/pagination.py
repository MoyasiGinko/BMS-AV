"""Standard pagination classes for Business OS REST API."""

from __future__ import annotations

from typing import Any

from rest_framework.pagination import CursorPagination, PageNumberPagination
from rest_framework.response import Response


class StandardCursorPagination(CursorPagination):
    """Cursor-based pagination for high-volume append-only records and ledgers."""

    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100
    ordering = "-created_at"


class StandardPageNumberPagination(PageNumberPagination):
    """Numbered page pagination with total count and page metadata."""

    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data: Any) -> Response:
        assert self.page is not None
        return Response(
            {
                "count": self.page.paginator.count,
                "total_pages": self.page.paginator.num_pages,
                "current_page": self.page.number,
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
                "results": data,
            }
        )
