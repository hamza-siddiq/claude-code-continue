"""Terminal.app integration via AppleScript."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from claude_code_continue.limit_parse import (
    SESSION_LIMIT_MARKER,
    SessionLimit,
    find_last_session_limit_line,
    is_active_session_limit,
    parse_session_limit,
)

# Let Terminal finish switching tabs before System Events sends keystrokes.
FOCUS_DELAY_SECONDS = 0.6

NO_LIMIT_TAB_MSG = (
    "No Terminal tab is currently at a Claude Code session limit. "
    "Leave the limited tab open at its prompt and run this soon after the limit appears."
)

STALE_LIMIT_TAB_MSG = (
    "Terminal tabs contain older session-limit messages in scrollback, but none "
    "appear to be actively limited right now."
)


@dataclass(frozen=True)
class TerminalTab:
    """A Terminal.app window/tab pair."""

    window_id: int
    tab_index: int
    contents: str
    title: str | None = None

    @property
    def label(self) -> str:
        return f"window id {self.window_id}, tab {self.tab_index}"

    def display_label(self, *, note: str | None = None) -> str:
        """Human-readable tab label for menus."""
        if self.title:
            base = f'Tab "{self.title}" (window {self.window_id}, tab {self.tab_index})'
        else:
            base = self.label
        if note:
            return f"{base} — {note}"
        return base

    def summary(self, limit: SessionLimit) -> str:
        """Human-readable description for menus and detect output."""
        if limit.timezone_name:
            reset = (
                f"{limit.reset_at_local.strftime('%I:%M %p').lstrip('0')} "
                f"({limit.timezone_name})"
            )
        else:
            reset = limit.reset_at_local.strftime("%I:%M %p").lstrip("0")
        return self.display_label(note=f"resets {reset}")


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


def _list_tab_refs() -> list[tuple[int, int, str | None]]:
    """Return (window_id, tab_index, title) for every readable Terminal tab."""
    script = '''
tell application "Terminal"
    set output to ""
    repeat with w from 1 to count of windows
        try
            set wid to id of window w
            set tabCount to count of tabs of window w
            repeat with t from 1 to tabCount
                try
                    set tabRef to tab t of window w
                    set tabTitle to custom title of tabRef
                    if tabTitle is missing value or tabTitle is "" then
                        set tabTitle to name of tabRef
                    end if
                    set output to output & (wid as string) & "|" & (t as string) & "|" & tabTitle & linefeed
                end try
            end repeat
        end try
    end repeat
    return output
end tell
'''
    raw = _run_applescript(script)
    refs: list[tuple[int, int, str | None]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        window_id, tab_index, title = parts
        title = title.strip() or None
        refs.append((int(window_id), int(tab_index), title))
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
    for window_id, tab_index, title in _list_tab_refs():
        contents = _get_tab_contents(window_id, tab_index)
        if contents is None:
            continue
        tabs.append(
            TerminalTab(
                window_id=window_id,
                tab_index=tab_index,
                contents=contents,
                title=title,
            )
        )
    return tabs


def _tab_has_session_limit_text(tab: TerminalTab) -> bool:
    if SESSION_LIMIT_MARKER not in tab.contents and "hit your session limit" not in tab.contents.lower():
        return False
    return find_last_session_limit_line(tab.contents) is not None


def _tab_has_active_session_limit(tab: TerminalTab) -> bool:
    if not _tab_has_session_limit_text(tab):
        return False
    return is_active_session_limit(tab.contents)


def _limit_tab_sort_key(item: tuple[TerminalTab, SessionLimit]) -> tuple[int, str]:
    tab, _ = item
    title = (tab.title or "").strip()
    if title.startswith(("✳", "*")):
        return (0, title.lower())
    return (1, title.lower())


def find_all_limit_tabs(
    tabs: list[TerminalTab] | None = None,
    *,
    active_only: bool = True,
) -> list[tuple[TerminalTab, SessionLimit]]:
    """Return Claude Code tabs with a session limit message."""
    tabs = tabs if tabs is not None else scan_tabs()
    results: list[tuple[TerminalTab, SessionLimit]] = []
    for tab in tabs:
        if not is_claude_code_tab(tab):
            continue
        if active_only:
            if not _tab_has_active_session_limit(tab):
                continue
        elif not _tab_has_session_limit_text(tab):
            continue
        limit = parse_session_limit(tab.contents)
        results.append((tab, limit))
    results.sort(key=_limit_tab_sort_key)
    return results


def raise_no_limit_tab_error(tabs: list[TerminalTab]) -> None:
    if not tabs:
        raise TerminalAppError(
            "Could not read any Terminal.app tabs. Ensure Terminal is running and "
            "Automation permission is granted."
        )
    if any(_tab_has_session_limit_text(tab) for tab in tabs):
        raise TerminalAppError(STALE_LIMIT_TAB_MSG)
    raise TerminalAppError(NO_LIMIT_TAB_MSG)


def find_limit_tab(tabs: list[TerminalTab] | None = None) -> tuple[TerminalTab, SessionLimit]:
    """Find the first tab whose scrollback contains a session limit message."""
    tabs = tabs if tabs is not None else scan_tabs()
    matches = find_all_limit_tabs(tabs)
    if not matches:
        raise_no_limit_tab_error(tabs)
    return matches[0]


_SHELL_TAB_TITLES = frozenset({"Terminal", "bash", "zsh", "sh"})

_CLAUDE_CODE_SCROLLBACK_MARKERS = (
    "plan mode on",
    "shift+tab to cycle",
    "← for agents",
    "✻ Worked for",
    "❯",
)


def is_claude_code_tab(tab: TerminalTab) -> bool:
    """Heuristic: tab scrollback or title looks like Claude Code."""
    if _tab_has_active_session_limit(tab):
        return True

    if tab.title:
        stripped = tab.title.strip()
        if stripped.startswith(("✳", "*")):
            return True

    tail = "\n".join(tab.contents.splitlines()[-80:])
    return any(marker in tail for marker in _CLAUDE_CODE_SCROLLBACK_MARKERS)


def list_continue_targets(
    tabs: list[TerminalTab],
    *,
    limit_tab: TerminalTab,
    limit_tabs: list[TerminalTab] | None = None,
) -> list[TerminalTab]:
    """Claude Code tabs for continue, with the limit-detected tab first."""
    ordered: list[TerminalTab] = [limit_tab]
    seen = {(limit_tab.window_id, limit_tab.tab_index)}

    for tab in limit_tabs or ():
        key = (tab.window_id, tab.tab_index)
        if key in seen:
            continue
        ordered.append(tab)
        seen.add(key)

    for tab in tabs:
        key = (tab.window_id, tab.tab_index)
        if key in seen:
            continue
        if not is_claude_code_tab(tab):
            continue
        ordered.append(tab)
        seen.add(key)
    return ordered


def find_tab_by_ref(
    window_id: int,
    tab_index: int,
    tabs: list[TerminalTab] | None = None,
) -> TerminalTab:
    """Re-resolve a tab by window id and tab index."""
    tabs = tabs if tabs is not None else scan_tabs()
    for tab in tabs:
        if tab.window_id == window_id and tab.tab_index == tab_index:
            return tab
    raise TerminalAppError(f"Tab window id {window_id}, tab {tab_index} not found.")


def find_limit_tab_by_ref(
    window_id: int,
    tab_index: int,
    tabs: list[TerminalTab] | None = None,
) -> tuple[TerminalTab, SessionLimit]:
    """Re-resolve a limit tab that is still actively at a session limit."""
    tab = find_tab_by_ref(window_id, tab_index, tabs)
    if not _tab_has_active_session_limit(tab):
        raise TerminalAppError(
            f"Tab {tab.label} is no longer actively at a session limit."
        )
    return tab, parse_session_limit(tab.contents)


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
