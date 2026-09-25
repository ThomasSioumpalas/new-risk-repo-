"""Single source of time. Dates are UTC calendar dates, so the result does not depend on the server's timezone."""

from __future__ import annotations

from datetime import UTC, date, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_today() -> date:
    return datetime.now(UTC).date()
