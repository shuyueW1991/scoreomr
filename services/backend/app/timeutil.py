"""Time helpers (all persistence is UTC ISO-8601)."""
from __future__ import annotations

from datetime import datetime, timezone

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
