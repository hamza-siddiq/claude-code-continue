"""Tests for watch helpers."""

from __future__ import annotations

import unittest

from claude_code_continue.watch import (
    _limits_share_reset_time,
    _parse_multi_choice,
    choose_continue_tabs,
    choose_limit_source,
)
from claude_code_continue.limit_parse import SessionLimit
from claude_code_continue.terminal_app import TerminalTab
from datetime import datetime


class ParseMultiChoiceTests(unittest.TestCase):
    def test_single_choice(self) -> None:
        self.assertEqual(_parse_multi_choice("2", 3), [2])

    def test_multiple_choices(self) -> None:
        self.assertEqual(_parse_multi_choice("1, 3", 3), [1, 3])

    def test_dedupes_invalid_duplicates(self) -> None:
        self.assertIsNone(_parse_multi_choice("1,1", 3))

    def test_rejects_out_of_range(self) -> None:
        self.assertIsNone(_parse_multi_choice("4", 3))
        self.assertIsNone(_parse_multi_choice("1,4", 3))

    def test_rejects_non_numeric(self) -> None:
        self.assertIsNone(_parse_multi_choice("1,all", 3))

    def test_rejects_empty(self) -> None:
        self.assertIsNone(_parse_multi_choice("", 3))
        self.assertIsNone(_parse_multi_choice(",", 3))


class LimitsShareResetTimeTests(unittest.TestCase):
    def _limit(self, hour: int = 4, minute: int = 50) -> SessionLimit:
        return SessionLimit(
            reset_at_local=datetime(2026, 6, 11, hour, minute),
            reset_at_source=datetime(2026, 6, 11, hour, minute),
            timezone_name="Asia/Karachi",
            matched_text="limit message",
        )

    def test_single_limit(self) -> None:
        tab = TerminalTab(window_id=1, tab_index=1, contents="", title="✳ a")
        self.assertTrue(_limits_share_reset_time([(tab, self._limit())]))

    def test_same_reset_time(self) -> None:
        tab_a = TerminalTab(window_id=1, tab_index=1, contents="", title="✳ a")
        tab_b = TerminalTab(window_id=2, tab_index=1, contents="", title="✳ b")
        candidates = [(tab_a, self._limit()), (tab_b, self._limit())]
        self.assertTrue(_limits_share_reset_time(candidates))

    def test_different_reset_time(self) -> None:
        tab_a = TerminalTab(window_id=1, tab_index=1, contents="", title="✳ a")
        tab_b = TerminalTab(window_id=2, tab_index=1, contents="", title="✳ b")
        candidates = [
            (tab_a, self._limit(minute=50)),
            (tab_b, self._limit(minute=55)),
        ]
        self.assertFalse(_limits_share_reset_time(candidates))


class ChooseLimitSourceTests(unittest.TestCase):
    def _limit(self) -> SessionLimit:
        return SessionLimit(
            reset_at_local=datetime(2026, 6, 11, 4, 50),
            reset_at_source=datetime(2026, 6, 11, 4, 50),
            timezone_name="Asia/Karachi",
            matched_text="limit message",
        )

    def test_same_reset_time_skips_prompt(self) -> None:
        tab_a = TerminalTab(window_id=1, tab_index=1, contents="", title="✳ a")
        tab_b = TerminalTab(window_id=2, tab_index=1, contents="", title="✳ b")
        limit_tab, limit = choose_limit_source([(tab_a, self._limit()), (tab_b, self._limit())])
        self.assertIs(limit_tab, tab_a)
        self.assertEqual(limit.reset_at_local, self._limit().reset_at_local)


class ChooseContinueTabsTests(unittest.TestCase):
    def _limit(self) -> SessionLimit:
        return SessionLimit(
            reset_at_local=datetime(2026, 6, 11, 14, 28),
            reset_at_source=datetime(2026, 6, 11, 14, 28),
            timezone_name="Asia/Karachi",
            matched_text="limit message",
        )

    def test_single_candidate(self) -> None:
        limit_tab = TerminalTab(window_id=1, tab_index=1, contents="", title="✳ a")
        tabs = choose_continue_tabs([limit_tab], limit_tab=limit_tab, limit=self._limit())
        self.assertEqual(tabs, (limit_tab,))

    def test_empty_candidates_uses_limit_tab(self) -> None:
        limit_tab = TerminalTab(window_id=1, tab_index=1, contents="", title="✳ a")
        tabs = choose_continue_tabs([], limit_tab=limit_tab, limit=self._limit())
        self.assertEqual(tabs, (limit_tab,))


if __name__ == "__main__":
    unittest.main()
