"""Shared date rules for scheduled clock-ins.

Dates are inclusive for ``startDate`` and ``endDate``. ``totalDays`` retains
its historical meaning: the schedule runs for that many calendar days starting
on ``startDate`` (or the first scheduler run when no start date was supplied).
"""
from __future__ import annotations

import datetime as _dt
import os
import re
from collections.abc import Mapping
from zoneinfo import ZoneInfo
from typing import Any


def _configured_today() -> _dt.date:
    """Return today's date in the scheduler's configured timezone."""
    tz_name = (os.getenv("SCHEDULER_TIMEZONE") or os.getenv("TZ") or "Asia/Shanghai").strip()
    try:
        timezone = ZoneInfo(tz_name)
    except Exception:
        timezone = ZoneInfo("Asia/Shanghai")
    return _dt.datetime.now(timezone).date()


def _parse_date(value: Any, field: str) -> _dt.date | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"schedule.{field} must be an ISO date string (YYYY-MM-DD)")
    try:
        parsed = _dt.date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"schedule.{field} must be a valid ISO date (YYYY-MM-DD)") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"schedule.{field} must use YYYY-MM-DD format")
    return parsed


def _default_holiday_checker(day: _dt.datetime) -> bool:
    """Load the existing holiday calendar only when a rule needs it."""
    from server.util.HelperFunctions import is_holiday

    return is_holiday(day)


def validate_clockin_schedule(clock_in: Any) -> dict[str, Any]:
    """Validate a clock-in config and return its normalized date-rule fields.

    Weekday values use ISO numbering (Monday=1 through Sunday=7). Missing
    weekdays inherit legacy ``customDays`` and then default to all seven days;
    an explicitly empty list is valid and means no scheduled weekdays.
    """
    if clock_in is None:
        clock_in = {}
    if not isinstance(clock_in, Mapping):
        raise ValueError("clock_in must be an object")
    schedule = clock_in.get("schedule", {})
    if schedule is None:
        schedule = {}
    if not isinstance(schedule, Mapping):
        raise ValueError("clock_in.schedule must be an object")

    start = _parse_date(schedule.get("startDate"), "startDate")
    end = _parse_date(schedule.get("endDate"), "endDate")
    if start is not None and end is not None and end < start:
        raise ValueError("schedule.endDate must be on or after schedule.startDate")

    total_days = schedule.get("totalDays")
    if total_days is not None:
        if isinstance(total_days, bool) or not isinstance(total_days, int) or total_days <= 0:
            raise ValueError("schedule.totalDays must be a positive integer")
        if total_days > 3650:
            raise ValueError("schedule.totalDays must be no greater than 3650")

    for field in ("startTime", "endTime"):
        value = schedule.get(field)
        if value is not None and value != "":
            if not isinstance(value, str) or re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value) is None:
                raise ValueError(f"schedule.{field} must use HH:mm format")

    weekdays = schedule.get("weekdays")
    if weekdays is None:
        weekdays = clock_in.get("customDays")
    if weekdays is None:
        weekdays = [1, 2, 3, 4, 5, 6, 7]
    if not isinstance(weekdays, (list, tuple)):
        raise ValueError("schedule.weekdays must be a list of ISO weekdays (1-7)")
    normalized_weekdays: list[int] = []
    for value in weekdays:
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 7:
            raise ValueError("schedule.weekdays values must be integers from 1 to 7")
        if value not in normalized_weekdays:
            normalized_weekdays.append(value)

    legacy_skip = clock_in.get("mode") == "holiday" and not clock_in.get("specialClockIn")
    skip_holidays = schedule.get("skipHolidays", legacy_skip)
    if not isinstance(skip_holidays, bool):
        raise ValueError("schedule.skipHolidays must be a boolean")

    return {
        "startDate": start,
        "endDate": end,
        "totalDays": total_days,
        "weekdays": tuple(normalized_weekdays),
        "skipHolidays": skip_holidays,
    }


def _as_date(day: Any) -> _dt.date:
    if isinstance(day, _dt.datetime):
        return day.date()
    if isinstance(day, _dt.date):
        return day
    parsed = _parse_date(day, "day")
    if parsed is None:
        raise ValueError("day must be a date")
    return parsed


def clockin_date_allowed(clock_in: Any, day: Any, holiday_checker=None) -> bool:
    """Return whether ``day`` satisfies the configured date/weekday rules.

    ``holiday_checker`` accepts a datetime and is consulted only when the
    ``skipHolidays`` rule (or the legacy holiday mode) is enabled. The default calendar is imported
    lazily, and may perform its existing cached I/O. Calendar data, rather than
    a weekday heuristic, determines non-working days so makeup work weekends
    remain eligible.
    """
    rules = validate_clockin_schedule(clock_in)
    current = _as_date(day)
    if rules["startDate"] is not None and current < rules["startDate"]:
        return False
    if rules["endDate"] is not None and current > rules["endDate"]:
        return False
    if rules["totalDays"] is not None and rules["startDate"] is not None:
        if (current - rules["startDate"]).days >= rules["totalDays"]:
            return False
    if current.isoweekday() not in rules["weekdays"]:
        return False
    if rules["skipHolidays"]:
        checker = _default_holiday_checker if holiday_checker is None else holiday_checker
        if checker(_dt.datetime.combine(current, _dt.time.min)):
            return False
    return True


def preview_clockin_dates(
    clock_in: Any,
    from_date: Any = None,
    limit: int = 10,
    holiday_checker=None,
) -> list[str]:
    """List the next allowed ISO dates, starting inclusively at ``from_date``.

    When omitted, ``from_date`` defaults to today in the configured scheduler
    timezone. The injected holiday checker is used for the same decisions as
    execution; the default checker may use its existing cached calendar I/O.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 0 <= limit <= 31:
        raise ValueError("limit must be an integer from 0 to 31")
    if limit == 0:
        # Still validate the schedule and supplied start date on zero-length previews.
        validate_clockin_schedule(clock_in)
        if from_date is not None:
            _as_date(from_date)
        return []
    current = _configured_today() if from_date is None else _as_date(from_date)
    # Validate once up-front so malformed configs fail even if no dates match.
    rules = validate_clockin_schedule(clock_in)
    if not rules["weekdays"]:
        return []
    if rules["startDate"] is not None:
        current = max(current, rules["startDate"])
    upper_bound = rules["endDate"]
    if rules["totalDays"] is not None and rules["startDate"] is not None:
        remaining = (_dt.date.max - rules["startDate"]).days
        total_days_end = rules["startDate"] + _dt.timedelta(days=min(rules["totalDays"] - 1, remaining))
        upper_bound = min(upper_bound, total_days_end) if upper_bound is not None else total_days_end
    if upper_bound is not None and current > upper_bound:
        return []
    dates: list[str] = []
    scanned = 0
    while len(dates) < limit and scanned < 3660 and (upper_bound is None or current <= upper_bound):
        if clockin_date_allowed(clock_in, current, holiday_checker=holiday_checker):
            dates.append(current.isoformat())
        if current == _dt.date.max:
            break
        current += _dt.timedelta(days=1)
        scanned += 1
    return dates
