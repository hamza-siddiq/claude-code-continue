"""CLI entry point for claude-code-continue."""

from __future__ import annotations

import argparse
import sys

from claude_code_continue import __version__
from claude_code_continue.terminal_app import TerminalAppError
from claude_code_continue.watch import detect_once, print_detect_result, run_watch


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claude-code-continue",
        description=(
            "Watch Terminal.app for Claude Code session limits and send "
            "continue when they reset."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    watch = subparsers.add_parser(
        "watch",
        help="Detect a session limit, wait for reset, then type continue",
    )
    watch.add_argument(
        "--at",
        metavar="TIME",
        help='Manual reset time (e.g. "2:28pm") instead of parsing from terminal',
    )
    watch.add_argument(
        "--allow-sleep",
        action="store_true",
        help="Allow the Mac to sleep during the wait",
    )
    watch.add_argument(
        "--poll",
        type=float,
        metavar="SECONDS",
        default=0,
        help="Re-scan tabs every N seconds until a limit message appears",
    )

    subparsers.add_parser(
        "detect",
        help="Find a session limit in Terminal tabs and print the reset time",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "detect":
            result = detect_once()
            print_detect_result(result)
            return 0

        if args.command == "watch":
            return run_watch(
                manual_at=args.at,
                allow_sleep=args.allow_sleep,
                poll_seconds=args.poll,
            )

    except TerminalAppError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(file=sys.stderr)
        return 130

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
