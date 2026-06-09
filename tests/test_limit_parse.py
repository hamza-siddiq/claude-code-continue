"""Tests for limit_parse.py."""

from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from claude_code_continue.limit_parse import (
    find_last_session_limit_line,
    find_session_limit_line,
    is_active_session_limit,
    is_tool_echo_limit_line,
    parse_session_limit,
)


class ParseSessionLimitTests(unittest.TestCase):
    def test_parse_with_timezone(self) -> None:
        text = "└ You've hit your session limit · resets 2:28pm (Asia/Karachi)"
        now = datetime(2026, 6, 9, 12, 0, tzinfo=ZoneInfo("Asia/Karachi"))
        result = parse_session_limit(text, now=now)

        self.assertEqual(result.timezone_name, "Asia/Karachi")
        self.assertEqual(result.reset_at_source.hour, 14)
        self.assertEqual(result.reset_at_source.minute, 28)
        self.assertEqual(result.reset_at_local.hour, 14)
        self.assertEqual(result.reset_at_local.minute, 28)
        self.assertIsNone(result.reset_at_local.tzinfo)

    def test_parse_without_minutes(self) -> None:
        text = "You've hit your session limit · resets 3pm (Asia/Karachi)"
        now = datetime(2026, 6, 9, 12, 0, tzinfo=ZoneInfo("Asia/Karachi"))
        result = parse_session_limit(text, now=now)

        self.assertEqual(result.reset_at_source.hour, 15)
        self.assertEqual(result.reset_at_source.minute, 0)

    def test_parse_rolls_to_next_day_when_past(self) -> None:
        text = "You've hit your session limit · resets 2:28pm (Asia/Karachi)"
        now = datetime(2026, 6, 9, 15, 0, tzinfo=ZoneInfo("Asia/Karachi"))
        result = parse_session_limit(text, now=now)

        self.assertEqual(result.reset_at_source.day, 10)
        self.assertEqual(result.reset_at_source.hour, 14)
        self.assertEqual(result.reset_at_source.minute, 28)

    def test_parse_without_timezone_uses_local(self) -> None:
        text = "You've hit your session limit · resets 4:15pm"
        local_tz = datetime.now().astimezone().tzinfo
        now = datetime(2026, 6, 9, 12, 0, tzinfo=local_tz)
        result = parse_session_limit(text, now=now)

        self.assertIsNone(result.timezone_name)
        self.assertEqual(result.reset_at_local.hour, 16)
        self.assertEqual(result.reset_at_local.minute, 15)

    def test_find_session_limit_line(self) -> None:
        text = (
            "some output\n"
            "└ You've hit your session limit · resets 2:20pm (Asia/Karachi)\n"
            "prompt >"
        )
        line = find_session_limit_line(text)
        self.assertIsNotNone(line)
        assert line is not None
        self.assertIn("session limit", line)

    def test_find_last_session_limit_line_prefers_latest(self) -> None:
        text = (
            "└ You've hit your session limit · resets 2:20pm (Asia/Karachi)\n"
            "continued working\n"
            "└ You've hit your session limit · resets 3:45pm (Asia/Karachi)\n"
            "prompt >"
        )
        line = find_last_session_limit_line(text)
        self.assertIsNotNone(line)
        assert line is not None
        self.assertIn("3:45pm", line)

    def test_tool_echo_limit_line_is_ignored(self) -> None:
        text = (
            "hamza@MacBook % ccc watch\n"
            "Found session limit in window id 31854, tab 1\n"
            "  Message: ⎿  You've hit your session limit · resets 7:20pm (Asia/Karachi)\n"
            "  1. Tab \"Terminal\" (window 31454, tab 1) — resets 7:20 PM (Asia/Karachi)\n"
        )
        self.assertTrue(is_tool_echo_limit_line("  Message: ⎿  You've hit your session limit"))
        self.assertIsNone(find_last_session_limit_line(text))

    def test_is_active_session_limit_near_tail(self) -> None:
        active = (
            "earlier output\n" * 20
            + "You've hit your session limit · resets 3:45pm (Asia/Karachi)\n"
            + "prompt >\n"
        )
        stale = (
            "You've hit your session limit · resets 2:20pm (Asia/Karachi)\n"
            + "lots more work after continuing\n" * 60
        )
        self.assertTrue(is_active_session_limit(active))
        self.assertFalse(is_active_session_limit(stale))

    def test_parse_session_limit_uses_latest_message(self) -> None:
        text = (
            "You've hit your session limit · resets 2:20pm (Asia/Karachi)\n"
            "You've hit your session limit · resets 3:45pm (Asia/Karachi)"
        )
        now = datetime(2026, 6, 9, 12, 0, tzinfo=ZoneInfo("Asia/Karachi"))
        result = parse_session_limit(text, now=now)
        self.assertEqual(result.reset_at_source.hour, 15)
        self.assertEqual(result.reset_at_source.minute, 45)

    def test_reset_at_local_subtracts_from_now(self) -> None:
        text = "You've hit your session limit · resets 2:28pm (Asia/Karachi)"
        now = datetime(2026, 6, 9, 12, 0, tzinfo=ZoneInfo("Asia/Karachi"))
        result = parse_session_limit(text, now=now)
        remaining = (result.reset_at_local - datetime.now()).total_seconds()
        self.assertIsInstance(remaining, float)

    def test_missing_limit_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_session_limit("no limit here")


if __name__ == "__main__":
    unittest.main()
