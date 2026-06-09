"""Terminal.app integration via AppleScript."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from claude_code_continue.limit_parse import (
    SESSION_LIMIT_MARKER,
    SessionLimit,
    find_session_limit_line,
    parse_session_limit,
)

# Let Terminal finish switching tabs before System Events sends keystrokes.
FOCUS_DELAY_SECONDS = 0.6


@dataclass(frozen=True)
class TerminalTab:
    """A Terminal.app window/tab pair."""

    window_id: int
    tab_index: int
    contents: str

    @property
    def label(self) -> str:
        return f"window id {self.window_id}, tab {self.tab_index}"


class TerminalAppError(RuntimeError):
    """Terminal.app scripting failed."""


def _run_applescript(script: str) -> str:
    proc = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or "unknown AppleScript error"
        raise TerminalAppError(stderr)
    return proc.stdout


def _list_tab_refs() -> list[tuple[int, int]]:
    """Return (window_id, tab_index) for every readable Terminal tab."""
    script = '''
tell application "Terminal"
    set output to ""
    repeat with w from 1 to count of windows
        try
            set wid to id of window w
            set tabCount to count of tabs of window w
            repeat with t from 1 to tabCount
                try
                    set output to output & (wid as string) & "," & (t as string) & linefeed
                end try
            end repeat
        end try
    end repeat
    return output
end tell
'''
    raw = _run_applescript(script)
    refs: list[tuple[int, int]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        window_id, tab_index = line.split(",", 1)
        refs.append((int(window_id), int(tab_index)))
    return refs


def _get_tab_contents(window_id: int, tab_index: int) -> str | None:
    script = f'''
tell application "Terminal"
    return contents of tab {tab_index} of window id {window_id}
end tell
'''
    proc = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def scan_tabs() -> list[TerminalTab]:
    """Return scrollback contents for every Terminal.app tab."""
    tabs: list[TerminalTab] = []
    for window_id, tab_index in _list_tab_refs():
        contents = _get_tab_contents(window_id, tab_index)
        if contents is None:
            continue
        tabs.append(
            TerminalTab(
                window_id=window_id,
                tab_index=tab_index,
                contents=contents,
            )
        )
    return tabs


def find_limit_tab(tabs: list[TerminalTab] | None = None) -> tuple[TerminalTab, SessionLimit]:
    """Find the first tab whose scrollback contains a session limit message."""
    tabs = tabs if tabs is not None else scan_tabs()
    for tab in tabs:
        if SESSION_LIMIT_MARKER not in tab.contents and "hit your session limit" not in tab.contents.lower():
            continue
        if not find_session_limit_line(tab.contents):
            continue
        limit = parse_session_limit(tab.contents)
        return tab, limit

    raise TerminalAppError(
        "No Terminal tab contains a Claude Code session limit message. "
        "Leave the limited Claude Code tab open and run this soon after the limit appears."
    )


def focus_tab(tab: TerminalTab) -> None:
    """Bring a Terminal tab to the front."""
    script = f'''
tell application "Terminal"
    activate
    set targetWindow to window id {tab.window_id}
    set index of targetWindow to 1
    set selected of tab {tab.tab_index} of targetWindow to true
end tell
'''
    _run_applescript(script)


def send_continue(tab: TerminalTab) -> None:
    """Focus the tab and type continue + Return at the Claude Code prompt."""
    # Single AppleScript block: select tab, wait for focus, then type.
    # Separate calls allowed keystrokes to land in the watcher's shell tab.
    script = f'''
tell application "Terminal"
    activate
    set targetWindow to window id {tab.window_id}
    set index of targetWindow to 1
    set selected of tab {tab.tab_index} of targetWindow to true
end tell

delay {FOCUS_DELAY_SECONDS}

tell application "System Events"
    tell process "Terminal"
        set frontmost to true
        keystroke "continue"
        key code 36
    end tell
end tell
'''
    _run_applescript(script)
