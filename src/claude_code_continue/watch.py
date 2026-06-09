"""Detect session limits, wait, and send continue."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from datetime import datetime

from claude_code_continue.schedule import next_run_at, parse_time_string, sleep_until
from claude_code_continue.terminal_app import (
    TerminalAppError,
    TerminalTab,
    find_limit_tab,
    scan_tabs,
    send_continue,
)

CONTINUE_ATTEMPT_COUNT = 3
CONTINUE_RETRY_GAPS_S = (30, 60)


@dataclass(frozen=True)
class DetectResult:
    tab: TerminalTab
    run_at: datetime
    timezone_name: str | None
    matched_text: str


def resolve_run_at_from_manual(manual_at: str) -> datetime:
    hour, minute = parse_time_string(manual_at)
    return next_run_at(hour, minute)


def detect_once() -> DetectResult:
    tab, limit = find_limit_tab()
    return DetectResult(
        tab=tab,
        run_at=limit.reset_at_local,
        timezone_name=limit.timezone_name,
        matched_text=limit.matched_text,
    )


def detect_with_poll(poll_seconds: float) -> DetectResult:
    """Re-scan Terminal tabs until a session limit message appears."""
    if poll_seconds <= 0:
        return detect_once()

    print(f"Polling Terminal tabs every {poll_seconds:g}s for a session limit...")
    while True:
        tabs = scan_tabs()
        try:
            tab, limit = find_limit_tab(tabs)
            return DetectResult(
                tab=tab,
                run_at=limit.reset_at_local,
                timezone_name=limit.timezone_name,
                matched_text=limit.matched_text,
            )
        except TerminalAppError:
            time.sleep(poll_seconds)


def print_detect_result(result: DetectResult) -> None:
    print(f"Found session limit in {result.tab.label}")
    print(f"  Message: {result.matched_text}")
    if result.timezone_name:
        print(
            f"  Reset: {result.run_at.strftime('%Y-%m-%d %I:%M %p')} "
            f"(from {result.timezone_name})"
        )
    else:
        print(f"  Reset: {result.run_at.strftime('%Y-%m-%d %I:%M %p')}")


def send_continue_with_retries(tab: TerminalTab) -> int:
    last_error: Exception | None = None
    for attempt in range(1, CONTINUE_ATTEMPT_COUNT + 1):
        if attempt > 1:
            gap = CONTINUE_RETRY_GAPS_S[attempt - 2]
            print(f"Waiting {gap}s before attempt {attempt}/{CONTINUE_ATTEMPT_COUNT}...")
            time.sleep(gap)

        print(f"Sending continue (attempt {attempt}/{CONTINUE_ATTEMPT_COUNT})...")
        try:
            # Re-find the tab in case windows were reordered while waiting.
            tab, _ = find_limit_tab()
            print(f"Targeting {tab.label}")
            send_continue(tab)
            if attempt > 1:
                print(f"Succeeded on attempt {attempt}.")
            else:
                print("Done.")
            return 0
        except TerminalAppError as exc:
            last_error = exc
            print(f"Error: {exc}", file=sys.stderr)
            if attempt < CONTINUE_ATTEMPT_COUNT:
                print("Will retry.", file=sys.stderr)

    if last_error is not None:
        print(f"Failed after {CONTINUE_ATTEMPT_COUNT} attempts: {last_error}", file=sys.stderr)
    return 1


def run_watch(
    *,
    manual_at: str | None = None,
    allow_sleep: bool = False,
    poll_seconds: float = 0,
) -> int:
    if manual_at:
        run_at = resolve_run_at_from_manual(manual_at)
        try:
            tab, _ = find_limit_tab()
        except TerminalAppError as exc:
            print(f"Warning: {exc}", file=sys.stderr)
            print(
                "Using --at without a detectable tab; continue will not be sent.",
                file=sys.stderr,
            )
            return 1
        print(f"Manual schedule: {run_at.strftime('%Y-%m-%d %I:%M %p')}")
        print(f"Target tab: {tab.label}")
    else:
        result = detect_with_poll(poll_seconds)
        tab = result.tab
        run_at = result.run_at
        print_detect_result(result)

    remaining = (run_at - datetime.now()).total_seconds()
    if remaining > 0:
        print(f"Waiting until {run_at.strftime('%Y-%m-%d %I:%M %p')}...")
        sleep_until(run_at, allow_sleep=allow_sleep)
    else:
        print("Reset time has already passed; sending continue now.")

    print("Scheduled time reached.")
    return send_continue_with_retries(tab)
