"""Detect session limits, wait, and send continue."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from datetime import datetime

from claude_code_continue.limit_parse import SessionLimit
from claude_code_continue.schedule import next_run_at, parse_time_string, sleep_until
from claude_code_continue.terminal_app import (
    TerminalAppError,
    TerminalTab,
    find_all_limit_tabs,
    find_tab_by_ref,
    list_continue_targets,
    raise_no_limit_tab_error,
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

    def summary(self) -> str:
        limit = SessionLimit(
            reset_at_local=self.run_at,
            reset_at_source=self.run_at,
            timezone_name=self.timezone_name,
            matched_text=self.matched_text,
        )
        return self.tab.summary(limit)


@dataclass(frozen=True)
class WatchPlan:
    """Schedule from a limit tab; continue may target a different tab."""

    limit_tab: TerminalTab
    limit: SessionLimit
    continue_tab: TerminalTab

    @property
    def run_at(self) -> datetime:
        return self.limit.reset_at_local


def resolve_run_at_from_manual(manual_at: str) -> datetime:
    hour, minute = parse_time_string(manual_at)
    return next_run_at(hour, minute)


def _detect_result(tab: TerminalTab, limit: SessionLimit) -> DetectResult:
    return DetectResult(
        tab=tab,
        run_at=limit.reset_at_local,
        timezone_name=limit.timezone_name,
        matched_text=limit.matched_text,
    )


def _format_reset(limit: SessionLimit) -> str:
    if limit.timezone_name:
        return (
            f"{limit.reset_at_local.strftime('%I:%M %p').lstrip('0')} "
            f"({limit.timezone_name})"
        )
    return limit.reset_at_local.strftime("%I:%M %p").lstrip("0")


def _prompt_choice(prompt: str, count: int) -> int:
    while True:
        try:
            raw = input(f"{prompt} [1-{count}]: ").strip()
            choice = int(raw)
        except ValueError:
            print("Enter a number from the list.")
            continue
        if 1 <= choice <= count:
            return choice
        print(f"Enter a number between 1 and {count}.")


def _choose_from_menu(
    title: str,
    options: list[str],
    *,
    non_tty_error: str,
) -> int:
    """Return a 1-based menu choice."""
    if len(options) == 1:
        return 1

    if not sys.stdin.isatty():
        print(title, file=sys.stderr)
        for index, option in enumerate(options, start=1):
            print(f"  {index}. {option}", file=sys.stderr)
        raise TerminalAppError(non_tty_error)

    print(title)
    for index, option in enumerate(options, start=1):
        print(f"  {index}. {option}")
    return _prompt_choice("Select tab", len(options))


def choose_limit_source(
    candidates: list[tuple[TerminalTab, SessionLimit]],
) -> tuple[TerminalTab, SessionLimit]:
    """Pick which active limit message sets the reset schedule."""
    if not candidates:
        raise_no_limit_tab_error(scan_tabs())
    if len(candidates) == 1:
        return candidates[0]

    options = [tab.summary(limit) for tab, limit in candidates]
    choice = _choose_from_menu(
        "Multiple Claude Code session limits found. Which reset time should be used?",
        options,
        non_tty_error=(
            "Multiple session limits found; run interactively in a terminal to choose a tab."
        ),
    )
    return candidates[choice - 1]


def choose_continue_tab(
    candidates: list[TerminalTab],
    *,
    limit_tab: TerminalTab,
    limit: SessionLimit,
) -> TerminalTab:
    """Pick which tab receives continue. Limit-detected tab is always option 1."""
    if not candidates:
        return limit_tab
    if len(candidates) == 1:
        return candidates[0]

    reset = _format_reset(limit)
    options: list[str] = []
    for tab in candidates:
        if tab.window_id == limit_tab.window_id and tab.tab_index == limit_tab.tab_index:
            options.append(tab.display_label(note=f"limit detected here, resets {reset}"))
        else:
            options.append(tab.display_label())

    choice = _choose_from_menu(
        "Select tab to send continue to:",
        options,
        non_tty_error=(
            "Multiple Claude Code tabs found; run interactively in a terminal to choose "
            "where continue should be sent."
        ),
    )
    return candidates[choice - 1]


def resolve_watch_plan(tabs: list[TerminalTab] | None = None) -> WatchPlan:
    """Detect the schedule from a limit tab and choose where to send continue."""
    tabs = tabs if tabs is not None else scan_tabs()
    limit_matches = find_all_limit_tabs(tabs)
    if not limit_matches:
        raise_no_limit_tab_error(tabs)

    limit_tab, limit = choose_limit_source(limit_matches)
    continue_candidates = list_continue_targets(tabs, limit_tab=limit_tab)
    continue_tab = choose_continue_tab(
        continue_candidates,
        limit_tab=limit_tab,
        limit=limit,
    )
    return WatchPlan(limit_tab=limit_tab, limit=limit, continue_tab=continue_tab)


def detect_all() -> list[DetectResult]:
    """Find every tab with a session limit message."""
    tabs = scan_tabs()
    matches = find_all_limit_tabs(tabs)
    if not matches:
        raise_no_limit_tab_error(tabs)
    return [_detect_result(tab, limit) for tab, limit in matches]


def detect_with_poll(poll_seconds: float) -> WatchPlan:
    """Re-scan Terminal tabs until a session limit message appears."""
    if poll_seconds <= 0:
        return resolve_watch_plan()

    print(f"Polling Terminal tabs every {poll_seconds:g}s for a session limit...")
    while True:
        tabs = scan_tabs()
        if find_all_limit_tabs(tabs):
            return resolve_watch_plan(tabs)
        time.sleep(poll_seconds)


def print_watch_plan(plan: WatchPlan) -> None:
    print(f"Found session limit in {plan.limit_tab.label}")
    print(f"  Message: {plan.limit.matched_text}")
    if plan.limit.timezone_name:
        print(
            f"  Reset: {plan.run_at.strftime('%Y-%m-%d %I:%M %p')} "
            f"(from {plan.limit.timezone_name})"
        )
    else:
        print(f"  Reset: {plan.run_at.strftime('%Y-%m-%d %I:%M %p')}")

    if (
        plan.continue_tab.window_id != plan.limit_tab.window_id
        or plan.continue_tab.tab_index != plan.limit_tab.tab_index
    ):
        print(f"Continue will be sent to {plan.continue_tab.display_label()}")


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


def print_detect_results(results: list[DetectResult]) -> None:
    if len(results) == 1:
        print_detect_result(results[0])
        return

    print(f"Found {len(results)} session limits:")
    for index, result in enumerate(results, start=1):
        print(f"  {index}. {result.summary()}")
        print(f"     Message: {result.matched_text}")


def send_continue_with_retries(tab: TerminalTab) -> int:
    window_id = tab.window_id
    tab_index = tab.tab_index
    last_error: Exception | None = None
    for attempt in range(1, CONTINUE_ATTEMPT_COUNT + 1):
        if attempt > 1:
            gap = CONTINUE_RETRY_GAPS_S[attempt - 2]
            print(f"Waiting {gap}s before attempt {attempt}/{CONTINUE_ATTEMPT_COUNT}...")
            time.sleep(gap)

        print(f"Sending continue (attempt {attempt}/{CONTINUE_ATTEMPT_COUNT})...")
        try:
            tab = find_tab_by_ref(window_id, tab_index)
            print(f"Targeting {tab.display_label()}")
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
            plan = resolve_watch_plan()
        except TerminalAppError as exc:
            print(f"Warning: {exc}", file=sys.stderr)
            print(
                "Using --at without a detectable tab; continue will not be sent.",
                file=sys.stderr,
            )
            return 1
        print(f"Manual schedule: {run_at.strftime('%Y-%m-%d %I:%M %p')}")
        print(f"Limit detected in {plan.limit_tab.display_label()}")
        print(f"Continue target: {plan.continue_tab.display_label()}")
    else:
        plan = detect_with_poll(poll_seconds)
        run_at = plan.run_at
        print_watch_plan(plan)

    remaining = (run_at - datetime.now()).total_seconds()
    if remaining > 0:
        print(f"Waiting until {run_at.strftime('%Y-%m-%d %I:%M %p')}...")
        sleep_until(run_at, allow_sleep=allow_sleep)
    else:
        print("Reset time has already passed; sending continue now.")

    print("Scheduled time reached.")
    return send_continue_with_retries(plan.continue_tab)
