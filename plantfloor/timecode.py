"""Wall-clock helpers. All pipeline math is in seconds from the first frame."""
from __future__ import annotations

from datetime import datetime, timedelta

_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M")


def parse_start(text: str) -> datetime:
    """Parse the wall-clock time of the first frame: 'YYYY-MM-DD HH:MM[:SS]'."""
    text = text.strip()
    for fmt in _FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f'start time must look like "2026-09-01 06:00:00", got {text!r}')


def at(start: datetime, seconds: float) -> datetime:
    return start + timedelta(seconds=seconds)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def clip_stamp(dt: datetime) -> str:
    """Filename-safe stamp used in chunk names, e.g. 2026-09-01_060000."""
    return dt.strftime("%Y-%m-%d_%H%M%S")
