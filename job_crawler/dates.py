from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .text import normalize_text


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    cleaned = value.strip()
    cleaned = cleaned.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_epoch_ms(value: int | float | str) -> datetime | None:
    try:
        millis = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc)


def parse_human_date(value: str) -> datetime | None:
    if not value:
        return None
    candidates = [
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%m-%d-%Y",
        "%b %d, %Y",
        "%B %d, %Y",
        "%d %b %Y",
        "%d %B %Y",
    ]
    for fmt in candidates:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_workday_posted(value: str, reference: datetime | None = None) -> datetime | None:
    if not value:
        return None
    ref = reference or now_utc()
    normalized = normalize_text(value)

    if "today" in normalized:
        return ref
    if "yesterday" in normalized:
        return ref - timedelta(days=1)

    match = re.search(r"(\d+)\s+day", normalized)
    if match:
        days = int(match.group(1))
        return ref - timedelta(days=days)

    if "posted on" in normalized:
        normalized = normalized.replace("posted on", "").strip()
    return parse_human_date(normalized) or parse_iso_datetime(value)


def is_recent(posted_at: datetime | None, max_age_days: int) -> bool:
    if posted_at is None:
        return False
    cutoff = now_utc() - timedelta(days=max_age_days)
    return posted_at >= cutoff
