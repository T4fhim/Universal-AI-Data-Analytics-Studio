# File: apps/api/uadas_api/web/pagination.py
"""Offset pagination with a hard cap, shared by every list endpoint.

Why hand-rolled instead of Ninja's ``@paginate``: the envelope (``items``/``total``/``limit``/
``offset``) must be the same typed schema in the OpenAPI document for every list, the cap must be
one number (``ApiConfig.max_page_size``), and the ordering must be explicit (an unordered page
repeats and skips rows). ``limit`` above the cap is a ``422``, not a silent clamp: a client that
asked for 10,000 rows should learn it, not receive 200 and think it has them all.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from ninja import Schema
from pydantic import Field

from uadas_api.web.config import ApiConfig

_cfg = (
    ApiConfig()
)  # the *documented* defaults go into the schema; runtime caps use api_config()

Limit = Annotated[int, Field(ge=1, le=_cfg.max_page_size)]
Offset = Annotated[int, Field(ge=0, le=_cfg.max_offset)]


class PageParams(Schema):
    """Query parameters of every list endpoint."""

    limit: Limit = _cfg.default_page_size
    offset: Offset = 0


class Page[T](Schema):
    """One page of a list, with the total so a client can render a pager."""

    items: list[T]
    total: int
    limit: int
    offset: int


def paginate[R](
    queryset: Any, params: PageParams, convert: Callable[[Any], R]
) -> dict[str, Any]:
    """Slice ``queryset`` (already ordered!) and map each row with ``convert``."""
    total = queryset.count()
    rows = queryset[params.offset : params.offset + params.limit]
    return {
        "items": [convert(row) for row in rows],
        "total": total,
        "limit": params.limit,
        "offset": params.offset,
    }
