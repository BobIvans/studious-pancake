"""Parser-owned subcommand identity, shared by installed CLI adapters."""

import argparse
from collections.abc import Sequence


class _DispatchParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def parsed_command(argv: Sequence[str]) -> str | None:
    parser = _DispatchParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--config-file")
    parser.add_argument("command", nargs="?")
    parsed, remaining = parser.parse_known_args(list(argv))
    # Unknown global options cannot manufacture a command from their value.
    if (
        remaining
        and argv
        and str(argv[0]).startswith("-")
        and not str(argv[0]).startswith("--config-file")
    ):
        return None
    return parsed.command


def requested_run_mode(argv: Sequence[str]) -> str | None:
    if parsed_command(argv) != "run":
        return None
    parser = _DispatchParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--config-file")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", add_help=False, allow_abbrev=False)
    run.add_argument("--mode", default="shadow")
    run.add_argument("--db-path")
    return parser.parse_known_args(list(argv))[0].mode
