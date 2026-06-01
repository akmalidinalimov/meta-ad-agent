"""Meta insight sync helpers (windowing + error-tolerant fetches).

Extracted from app.py so the Meta router and any future scheduler can share the
chunked-insight logic. Pure I/O orchestration over meta_client.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .meta_client import MetaApiError, get_insights

SYNC_END_DATE = date.today()


def normalize_sync_days(days: int) -> int:
    if days <= 0:
        return 90
    return min(days, 186)


def build_sync_windows(*, days: int, end_date: date, chunk_days: int = 7) -> list[tuple[date, date]]:
    days = normalize_sync_days(days)
    start = end_date - timedelta(days=days - 1)
    windows: list[tuple[date, date]] = []
    current = start
    while current <= end_date:
        chunk_end = min(current + timedelta(days=chunk_days - 1), end_date)
        windows.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return windows


async def safe_insights(config: Any, breakdowns: list[str]) -> list[dict[str, Any]]:
    try:
        return await get_insights(config, breakdowns=breakdowns)
    except MetaApiError as error:
        return [{"sync_error": str(error), "breakdowns": ",".join(breakdowns)}]


async def safe_chunked_insights(
    config: Any,
    name: str,
    breakdowns: list[str] | None,
    *,
    days: int = 90,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for current, chunk_end in build_sync_windows(days=days, end_date=SYNC_END_DATE):
        try:
            rows.extend(await get_insights(config, breakdowns=breakdowns, since=current.isoformat(), until=chunk_end.isoformat()))
        except MetaApiError as error:
            errors.append({
                "sync_error": str(error),
                "source": name,
                "since": current.isoformat(),
                "until": chunk_end.isoformat(),
            })

    return rows or errors


async def safe_list(name: str, awaitable: Any) -> list[dict[str, Any]]:
    try:
        return await awaitable
    except MetaApiError as error:
        return [{"sync_error": str(error), "source": name}]
