"""PR-189 automation-safe wrapper for the installed flashloan-bot CLI."""

from __future__ import annotations

import sys
from typing import Sequence

from src import automation_cli_pr189
from src import cli as legacy_cli


def _rewrite_legacy_preflight(args: list[str]) -> list[str] | None:
    if not args:
        return None
    if args[0] == "paper-vertical-preflight":
        forwarded = ["paper-vertical", "check"]
        forwarded.extend(item for item in args[1:] if item != "--json")
        return forwarded
    return None


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    if args and args[0] == "checks":
        return automation_cli_pr189.main(args[1:])
    if args and args[0] == "paper-vertical":
        return automation_cli_pr189.main(args)
    if args and args[0] == "readiness":
        return automation_cli_pr189.main(["production-debt", *args[1:]])
    if args and args[0] == "release-soak":
        return automation_cli_pr189.main(args)
    rewritten = _rewrite_legacy_preflight(args)
    if rewritten is not None:
        return automation_cli_pr189.main(rewritten)
    return legacy_cli.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
