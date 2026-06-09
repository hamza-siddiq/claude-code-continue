"""macOS sleep/wake helpers for long scheduled waits."""

from __future__ import annotations

from datetime import datetime
import subprocess
import sys

# Try to wake the system this many seconds before the target (when far away).
WAKE_LEAD_SECONDS = 120
# Do not call pmset when less than this remains (wake + continue is imminent).
MIN_WAKE_SCHEDULE_SECONDS = 300
# Prevent idle sleep in the final window so a running Mac does not doze off.
CAFFEINATE_LEAD_SECONDS = 180
WAKE_EVENT_OWNER = "claude-code-continue"


def _pmset_datetime(value: datetime) -> str:
    return value.strftime("%m/%d/%y %H:%M:%S")


def try_schedule_wake_at(when: datetime) -> bool:
    """Ask macOS to wake at an absolute local time (best-effort)."""
    proc = subprocess.run(
        [
            "pmset",
            "schedule",
            "wakeorpoweron",
            _pmset_datetime(when),
            WAKE_EVENT_OWNER,
        ],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def start_idle_sleep_preventer(seconds: float) -> subprocess.Popen | None:
    """Start a bounded caffeinate process that prevents idle system sleep."""
    secs = max(1, int(seconds) + 15)
    try:
        return subprocess.Popen(
            ["caffeinate", "-i", "-t", str(secs)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None


def stop_sleep_preventer(proc: subprocess.Popen | None) -> None:
    """Stop a caffeinate process started by start_idle_sleep_preventer."""
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        proc.kill()


def prevent_idle_sleep(seconds: float) -> None:
    """Keep the system awake for `seconds` using caffeinate (no admin)."""
    start_idle_sleep_preventer(seconds)


def format_wait_duration(seconds: float) -> str:
    if seconds < 90:
        return f"{int(seconds)}s"
    minutes = int(seconds // 60)
    if minutes < 90:
        return f"{minutes} min"
    hours, rem = divmod(minutes, 60)
    if rem:
        return f"{hours} hr {rem} min"
    return f"{hours} hr"


def notify_resume_after_sleep() -> None:
    print(
        "Resumed after sleep; continuing toward scheduled time...",
        file=sys.stderr,
    )
