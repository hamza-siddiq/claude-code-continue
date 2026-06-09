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


@dataclass(frozen=True)
class TerminalTab:
    """A Terminal.app window/tab pair."""

    window_index: int
    tab_index: int
    contents: str

    @property
    def label(self) -> str:
        return f"window {self.window_index}, tab {self.tab_index}"


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


def _list_tab_indices() -> list[tuple[int, int]]:
    script = '''
tell application "Terminal"
    set pairs to ""
    repeat with w in windows
        set widx to index of w
        repeat with t in tabs of w
            set pairs to pairs & (widx as string) & "," & (index of t as string) & linefeed
        end repeat
    end repeat
    return pairs
end tell
'''
    raw = _run_applescript(script)
    indices: list[tuple[int, int]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        window_index, tab_index = line.split(",", 1)
        indices.append((int(window_index), int(tab_index)))
    return indices


def _get_tab_contents(window_index: int, tab_index: int) -> str:
    script = f'''
tell application "Terminal"
    return contents of tab {tab_index} of window {window_index}
end tell
'''
    return _run_applescript(script)


def scan_tabs() -> list[TerminalTab]:
    """Return scrollback contents for every Terminal.app tab."""
    tabs: list[TerminalTab] = []
    for window_index, tab_index in _list_tab_indices():
        contents = _get_tab_contents(window_index, tab_index)
        tabs.append(
            TerminalTab(
                window_index=window_index,
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
    set targetWindow to window {tab.window_index}
    set index of targetWindow to 1
    set selected of tab {tab.tab_index} of targetWindow to true
end tell
'''
    _run_applescript(script)


def send_continue(tab: TerminalTab) -> None:
    """Focus the tab and type continue + Return at the Claude Code prompt."""
    focus_tab(tab)
    script = '''
tell application "System Events"
    tell process "Terminal"
        set frontmost to true
        keystroke "continue"
        key code 36
    end tell
end tell
'''
    _run_applescript(script)
