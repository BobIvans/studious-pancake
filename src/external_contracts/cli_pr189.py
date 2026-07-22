"""PR-189 automation-safe wrapper for flashloan-contracts."""

from __future__ import annotations

import sys
from typing import Sequence

from src import automation_cli_pr189
from src.external_contracts import cli as legacy_cli


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    if args and args[0] == "provider-readiness":
        forwarded = list(args)
        if len(forwarded) == 1 or forwarded[1].startswith("-"):
            forwarded.insert(1, "check")
        forwarded = [item for item in forwarded if item != "--require-ready"]
        return automation_cli_pr189.main(forwarded)
    return legacy_cli.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
