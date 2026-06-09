"""Tests for terminal_app helpers."""

from __future__ import annotations

import unittest

from claude_code_continue.terminal_app import (
    TerminalTab,
    is_claude_code_tab,
    list_continue_targets,
)


class TerminalTabHelpersTests(unittest.TestCase):
    def test_is_claude_code_tab_from_title(self) -> None:
        tab = TerminalTab(
            window_id=1,
            tab_index=1,
            contents="hamza@MacBook % ls\n",
            title="✳ my-project",
        )
        self.assertTrue(is_claude_code_tab(tab))

    def test_is_claude_code_tab_from_star_title(self) -> None:
        tab = TerminalTab(
            window_id=1,
            tab_index=1,
            contents="working\n",
            title="*k6-slo-staging-rerun - node",
        )
        self.assertTrue(is_claude_code_tab(tab))

    def test_is_claude_code_tab_from_scrollback(self) -> None:
        tab = TerminalTab(
            window_id=1,
            tab_index=1,
            contents="some output\n  ⏸ plan mode on (shift+tab to cycle)\n",
            title=None,
        )
        self.assertTrue(is_claude_code_tab(tab))

    def test_is_claude_code_tab_rejects_plain_shell(self) -> None:
        tab = TerminalTab(
            window_id=1,
            tab_index=1,
            contents="hamza@MacBook % pip install -e .\n",
            title="Terminal",
        )
        self.assertFalse(is_claude_code_tab(tab))

    def test_is_claude_code_tab_rejects_ccc_watch_echo(self) -> None:
        tab = TerminalTab(
            window_id=31454,
            tab_index=1,
            contents=(
                "hamza@MacBook % ccc watch\n"
                "Found session limit in window id 31854, tab 1\n"
                "  Message: ⎿  You've hit your session limit · resets 7:20pm (Asia/Karachi)\n"
            ),
            title="Terminal",
        )
        self.assertFalse(is_claude_code_tab(tab))

    def test_list_continue_targets_puts_limit_tab_first(self) -> None:
        limit_tab = TerminalTab(
            window_id=100,
            tab_index=1,
            contents="You've hit your session limit · resets 7:20pm\n❯ \n",
            title="✳ limited-project",
        )
        other_tab = TerminalTab(
            window_id=200,
            tab_index=1,
            contents="working along\n❯ \n  ⏸ plan mode on\n",
            title="✳ other-project",
        )
        shell_tab = TerminalTab(
            window_id=300,
            tab_index=1,
            contents="hamza@MacBook % ccc watch\n",
            title="Terminal",
        )

        targets = list_continue_targets(
            [other_tab, shell_tab, limit_tab],
            limit_tab=limit_tab,
        )
        self.assertEqual([tab.window_id for tab in targets], [100, 200])


if __name__ == "__main__":
    unittest.main()
