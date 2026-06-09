"""Parse Claude Code terminal session-limit messages."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

SESSION_LIMIT_MARKER = "You've hit your session limit"

# Limit must appear near the end of scrollback to count as the current state.
ACTIVE_LIMIT_TAIL_LINES = 50

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


def _as_naive_local(dt: datetime) -> datetime:
    """Convert an aware datetime to naive local time for scheduling."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone().replace(tzinfo=None)


def _to_24h(hour: int, ampm: str) -> int:
    ampm = ampm.lower()
    if ampm == "pm" and hour != 12:
        return hour + 12
    if ampm == "am" and hour == 12:
        return 0
    return hour


def is_tool_echo_limit_line(line: str) -> bool:
    """True for ccc watch/detect output copied into a shell tab."""
    stripped = line.strip()
    if stripped.startswith(("Message:", "Found session limit in")):
        return True
    if stripped.startswith("Multiple Claude Code session limits found"):
        return True
    if re.match(r"^\d+\.\s+Tab \"", stripped):
        return True
    return False


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


def is_active_session_limit(
    text: str,
    *,
    tail_lines: int = ACTIVE_LIMIT_TAIL_LINES,
) -> bool:
    """Return True when the latest session limit is near the end of scrollback."""
    if find_last_session_limit_line(text) is None:
        return False

    lines = text.splitlines()
    if not lines:
        return False

    min_index = max(0, len(lines) - tail_lines)
    for index in range(len(lines) - 1, -1, -1):
        line = lines[index]
        if is_tool_echo_limit_line(line):
            continue
        if _SESSION_LIMIT_RE.search(line):
            return index >= min_index
    return False


def find_last_session_limit_line(text: str) -> str | None:
    """Return the last line containing a session limit message, if any."""
    last_line: str | None = None
    for line in text.splitlines():
        if is_tool_echo_limit_line(line):
            continue
        if SESSION_LIMIT_MARKER in line or "hit your session limit" in line.lower():
            if _SESSION_LIMIT_RE.search(line):
                last_line = line.strip()
    if last_line is not None:
        return last_line

    for match in reversed(list(_SESSION_LIMIT_RE.finditer(text))):
        start = text.rfind("\n", 0, match.start()) + 1
        end = text.find("\n", match.start())
        if end == -1:
            end = len(text)
        line = text[start:end]
        if not is_tool_echo_limit_line(line):
            return match.group(0).strip()
    return None


def parse_session_limit(
    text: str,
    *,
    now: datetime | None = None,
) -> SessionLimit:
    """Parse a session limit message and return the next reset as local time."""
    line = find_last_session_limit_line(text)
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
        reset_at_local=_as_naive_local(candidate),
        reset_at_source=candidate,
        timezone_name=tz_name.strip() if tz_name else None,
        matched_text=line,
    )
