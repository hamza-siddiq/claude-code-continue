"""Parse Claude Code terminal session-limit messages."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

SESSION_LIMIT_MARKER = "You've hit your session limit"

_SESSION_LIMIT_RE = re.compile(
    r"You(?:'|\u2019)ve hit your session limit\s*[·•]\s*resets\s+"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*"
    r"(?P<ampm>am|pm)"
    r"(?:\s*\((?P<timezone>[^)]+)\))?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SessionLimit:
    """Parsed session limit from terminal scrollback."""

    reset_at_local: datetime
    reset_at_source: datetime
    timezone_name: str | None
    matched_text: str


def _to_24h(hour: int, ampm: str) -> int:
    ampm = ampm.lower()
    if ampm == "pm" and hour != 12:
        return hour + 12
    if ampm == "am" and hour == 12:
        return 0
    return hour


def find_session_limit_line(text: str) -> str | None:
    """Return the first line containing a session limit message, if any."""
    for line in text.splitlines():
        if SESSION_LIMIT_MARKER in line or "hit your session limit" in line.lower():
            if _SESSION_LIMIT_RE.search(line):
                return line.strip()
    match = _SESSION_LIMIT_RE.search(text)
    if match:
        return match.group(0).strip()
    return None


def parse_session_limit(
    text: str,
    *,
    now: datetime | None = None,
) -> SessionLimit:
    """Parse a session limit message and return the next reset as local time."""
    line = find_session_limit_line(text)
    if not line:
        raise ValueError(
            f'No session limit message found. Expected text like: '
            f'"{SESSION_LIMIT_MARKER} · resets 2:28pm (Asia/Karachi)"'
        )

    match = _SESSION_LIMIT_RE.search(line)
    if not match:
        raise ValueError(f'Could not parse reset time from "{line}"')

    hour = _to_24h(int(match.group("hour")), match.group("ampm"))
    minute = int(match.group("minute") or 0)
    tz_name = match.group("timezone")

    if tz_name:
        tz = ZoneInfo(tz_name.strip())
        ref = datetime.now(tz) if now is None else now.astimezone(tz)
    else:
        tz = datetime.now().astimezone().tzinfo
        ref = datetime.now(tz) if now is None else now.astimezone(tz)

    candidate = ref.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= ref:
        candidate += timedelta(days=1)

    return SessionLimit(
        reset_at_local=candidate.astimezone(),
        reset_at_source=candidate,
        timezone_name=tz_name.strip() if tz_name else None,
        matched_text=line,
    )
