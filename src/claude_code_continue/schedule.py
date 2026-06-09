"""Parse clock times and sleep until the next occurrence."""

from __future__ import annotations

import re
import sys
import time
from datetime import datetime, timedelta

from claude_code_continue.power import (
    CAFFEINATE_LEAD_SECONDS,
    MIN_WAKE_SCHEDULE_SECONDS,
    WAKE_LEAD_SECONDS,
    format_wait_duration,
    notify_resume_after_sleep,
    prevent_idle_sleep,
    start_idle_sleep_preventer,
    stop_sleep_preventer,
    try_schedule_wake_at,
)

_TIME_RE = re.compile(
    r"^\s*"
    r"(?P<hour>\d{1,2})"
    r"(?::(?P<minute>\d{1,2}))?"
    r"\s*"
    r"(?P<ampm>am|pm)?"
    r"\s*$",
    re.IGNORECASE,
)


def parse_time_string(text: str) -> tuple[int, int]:
    """Parse strings like '4:20pm', '7:30 am', '16:20'."""
    match = _TIME_RE.match(text.strip())
    if not match:
        raise ValueError(
            f'Invalid time "{text}". Use formats like 4:20pm, 7:30 am, or 16:20.'
        )

    hour = int(match.group("hour"))
    minute = int(match.group("minute") or 0)
    ampm = (match.group("ampm") or "").lower()

    if minute < 0 or minute > 59:
        raise ValueError("Minute must be between 0 and 59")

    if ampm:
        if hour < 1 or hour > 12:
            raise ValueError("Hour must be between 1 and 12 when using am/pm")
        if ampm == "pm" and hour != 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
    elif hour > 23:
        raise ValueError("Hour must be between 0 and 23 for 24-hour format")

    return hour, minute


def next_run_at(
    hour: int,
    minute: int,
    *,
    today_only: bool = False,
    now: datetime | None = None,
) -> datetime:
    """Return the next datetime at the given local clock time."""
    now = now or datetime.now()
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        if today_only:
            raise ValueError(
                f"Time {hour:02d}:{minute:02d} has already passed today."
            )
        candidate += timedelta(days=1)
    return candidate


def _wake_at_before_target(target: datetime) -> datetime:
    """Local clock time when macOS should wake before the target."""
    return target - timedelta(seconds=CAFFEINATE_LEAD_SECONDS)


def _start_sleep_preventer(remaining: float):
    proc = start_idle_sleep_preventer(remaining)
    if proc is None:
        print(
            "Could not start caffeinate; if the Mac sleeps, this run may wait "
            "until you wake it.",
            file=sys.stderr,
        )
        return None
    print(
        f"Keeping Mac awake for {format_wait_duration(remaining)} "
        "(display may still sleep).",
        file=sys.stderr,
    )
    return proc


def sleep_until(target: datetime, *, allow_sleep: bool = False) -> None:
    """Block until `target`, allowing the Mac to sleep most of the wait.

    By default, keeps the system from idle-sleeping if macOS will not accept a
    scheduled wake event. With allow_sleep=True, the Mac may sleep; if the wake
    event cannot be registered, the process resumes only after something else
    wakes the system.
    """
    wake_attempted = False
    wake_scheduled = False
    sleep_preventer = None
    completed = False
    last_tick = datetime.now()

    try:
        while True:
            now = datetime.now()
            remaining = (target - now).total_seconds()
            if remaining <= 0:
                completed = True
                return

            tick_gap = (now - last_tick).total_seconds()
            if tick_gap > 90:
                notify_resume_after_sleep()

            if not wake_attempted and remaining >= MIN_WAKE_SCHEDULE_SECONDS:
                wake_attempted = True
                wake_at = _wake_at_before_target(target)
                wake_in = max(WAKE_LEAD_SECONDS, (wake_at - now).total_seconds())
                if try_schedule_wake_at(wake_at):
                    print(
                        f"Scheduled system wake for "
                        f"{wake_at.strftime('%Y-%m-%d %I:%M %p')} "
                        f"({format_wait_duration(wake_in)} from now).",
                        file=sys.stderr,
                    )
                    wake_scheduled = True
                elif allow_sleep:
                    print(
                        "Could not schedule a system wake; if the Mac sleeps, "
                        "this run may wait until you wake it.",
                        file=sys.stderr,
                    )
                else:
                    print(
                        "Could not schedule a system wake; falling back to "
                        "caffeinate.",
                        file=sys.stderr,
                    )
                    sleep_preventer = _start_sleep_preventer(remaining)

            if (
                not allow_sleep
                and not wake_scheduled
                and sleep_preventer is None
                and remaining < MIN_WAKE_SCHEDULE_SECONDS
            ):
                sleep_preventer = _start_sleep_preventer(remaining)

            if remaining <= CAFFEINATE_LEAD_SECONDS:
                if sleep_preventer is None:
                    prevent_idle_sleep(remaining)
                while (target - datetime.now()).total_seconds() > 0:
                    time.sleep(0.25)
                completed = True
                return

            last_tick = now
            chunk = min(remaining - CAFFEINATE_LEAD_SECONDS, 60)
            time.sleep(max(chunk, 0.25))
    finally:
        if not completed:
            stop_sleep_preventer(sleep_preventer)
