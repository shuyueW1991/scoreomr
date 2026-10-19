"""Time and day-boundary helpers (all persistence is UTC ISO-8601)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(moment: datetime | None = None) -> str:
    moment = moment or utcnow()
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def day_key(moment: datetime, tz: ZoneInfo) -> str:
    return moment.astimezone(tz).date().isoformat()


def next_reset(moment: datetime, tz: ZoneInfo) -> datetime:
    local = moment.astimezone(tz)
    tomorrow = (local + timedelta(days=1)).date()
    return datetime.combine(tomorrow, datetime.min.time(), tzinfo=tz).astimezone(UTC)


def seconds_until_reset(moment: datetime, tz: ZoneInfo) -> int:
    return max(0, int((next_reset(moment, tz) - moment).total_seconds()))
