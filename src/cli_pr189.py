"""Automation-safe installed CLI with the canonical sender-free paper root."""

from __future__ import annotations

import os
import sys
from typing import Sequence

from src import automation_cli_pr189
from src import cli as legacy_cli
from src.canonical_paper import cli as canonical_paper_cli


PAPER_DB_ENV = "FLASHLOAN_PAPER_SERVICE_DB"


def _rewrite_legacy_preflight(args: list[str]) -> list[str] | None:
    if not args:
        return None
    if args[0] == "paper-vertical-preflight":
        forwarded = ["paper-vertical", "check"]
        forwarded.extend(item for item in args[1:] if item != "--json")
        return forwarded
    return None


def _has_option(args: list[str], name: str) -> bool:
    return name in args or any(item.startswith(f"{name}=") for item in args)


def _canonical_paper_args(args: list[str]) -> list[str] | None:
    """Translate the installed ``run --mode paper`` surface to one paper root."""

    try:
        run_index = args.index("run")
    except ValueError:
        return None

    prefix = args[:run_index]
    tail = args[run_index + 1 :]
    forwarded: list[str] = []

    index = 0
    while index < len(prefix):
        item = prefix[index]
        if item == "--config-file":
            if index + 1 >= len(prefix):
                return None
            forwarded.extend((item, prefix[index + 1]))
            index += 2
            continue
        if item.startswith("--config-file="):
            forwarded.append(item)
            index += 1
            continue
        return None

    mode: str | None = None
    index = 0
    while index < len(tail):
        item = tail[index]
        if item == "--mode":
            if index + 1 >= len(tail):
                return None
            mode = tail[index + 1]
            index += 2
            continue
        if item.startswith("--mode="):
            mode = item.partition("=")[2]
            index += 1
            continue
        forwarded.append(item)
        index += 1

    if mode != "paper":
        return None
    if not _has_option(forwarded, "--db-path"):
        db_path = os.environ.get(PAPER_DB_ENV)
        if db_path:
            forwarded.extend(("--db-path", db_path))
    return forwarded


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    canonical_paper_args = _canonical_paper_args(args)
    if canonical_paper_args is not None:
        return canonical_paper_cli.main(canonical_paper_args)
    if args and args[0] == "checks":
        return automation_cli_pr189.main(args[1:])
    if args and args[0] == "paper-vertical":
        return automation_cli_pr189.main(args)
    if args and args[0] == "readiness":
        return automation_cli_pr189.main(["production-debt", *args[1:]])
    if args and args[0] == "release-soak":
        return automation_cli_pr189.main(args)
    if args and args[0] == "shadow-soak":
        from src.mpr_close_04_runtime import shadow_soak_cli_main

        return shadow_soak_cli_main(args[1:])
    rewritten = _rewrite_legacy_preflight(args)
    if rewritten is not None:
        return automation_cli_pr189.main(rewritten)
    return legacy_cli.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
