"""Automation-safe installed CLI with the active sender-free paper root."""

from __future__ import annotations

import os
import sys
from typing import Sequence

from src import automation_cli_pr189
from src import cli as legacy_cli


PAPER_DB_ENV = "FLASHLOAN_PAPER_SERVICE_DB"


def _rewrite_legacy_preflight(args: list[str]) -> list[str] | None:
    if not args:
        return None
    if args[0] == "paper-vertical-preflight":
        forwarded = ["paper-vertical", "check"]
        forwarded.extend(item for item in args[1:] if item != "--json")
        return forwarded
    return None


def _is_run_mode_paper(args: list[str]) -> bool:
    if not args or args[0] != "run":
        return False
    for index, item in enumerate(args[1:], start=1):
        if item == "--mode":
            return index + 1 < len(args) and args[index + 1] == "paper"
        if item == "--mode=paper":
            return True
    return False


def _consume_legacy_paper_db_path(args: list[str]) -> list[str]:
    """Map the old canonical-paper ``--db-path`` flag to the active service env.

    MPR-CLOSE-24 intentionally routes installed paper execution into the active
    durable paper service. Older smoke tests and scripts still pass ``--db-path``
    to ``flashloan-bot run --mode paper`` from the previous canonical-paper CLI;
    keep that hidden compatibility path without exposing a second paper root.
    """

    if not _is_run_mode_paper(args):
        return args
    forwarded: list[str] = []
    index = 0
    while index < len(args):
        item = args[index]
        if item == "--db-path":
            if index + 1 < len(args):
                os.environ[PAPER_DB_ENV] = args[index + 1]
                index += 2
                continue
        elif item.startswith("--db-path="):
            os.environ[PAPER_DB_ENV] = item.partition("=")[2]
            index += 1
            continue
        forwarded.append(item)
        index += 1
    return forwarded


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
    return legacy_cli.main(_consume_legacy_paper_db_path(args))


if __name__ == "__main__":
    raise SystemExit(main())
